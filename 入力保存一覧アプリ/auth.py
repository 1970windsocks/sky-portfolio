import json
import os
import secrets
import urllib.request
from datetime import datetime, timedelta, timezone

import bcrypt
import psycopg
from psycopg.rows import dict_row

import audit

LOGIN_ATTEMPT_LIMIT = 5
LOGIN_ATTEMPT_WINDOW_MINUTES = 15
RESET_REQUEST_LIMIT = 3
RESET_REQUEST_WINDOW_MINUTES = 60


def _connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password, password_hash):
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def send_email(to, subject, body):
    # RailwayのFree/Trial/Hobbyプランは outbound SMTP が塞がれているため、
    # HTTPS(443)で送れるResendのAPIを使う(Railway公式が推奨する方式)。
    api_key = os.environ["RESEND_API_KEY"]
    from_addr = os.environ.get("RESEND_FROM", "onboarding@resend.dev")

    payload = json.dumps(
        {"from": from_addr, "to": [to], "subject": subject, "text": body}
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # User-Agentが無いとCloudflareにボット扱いされ403(error code: 1010)になる
            "User-Agent": "input-save-app/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


def _base_url():
    return os.environ.get("APP_BASE_URL", "").rstrip("/")


def _create_token(user_id, purpose, ttl_hours):
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO auth_tokens (user_id, token, purpose, expires_at) VALUES (%s, %s, %s, %s)",
            (user_id, token, purpose, expires_at),
        )
    return token


def get_user_by_username(username):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = %s", (username,)).fetchone()
    return dict(row) if row else None


def get_user_by_email(email):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = %s", (email,)).fetchone()
    return dict(row) if row else None


def create_user(username, email, password):
    """新規登録。戻り値: (成功したか, メッセージ)"""
    if get_user_by_username(username):
        return False, "そのユーザー名は既に使われています"
    if get_user_by_email(email):
        return False, "そのメールアドレスは既に登録されています"

    password_hash = hash_password(password)
    with _connect() as conn:
        row = conn.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s) RETURNING id",
            (username, email, password_hash),
        ).fetchone()
    user_id = row["id"]

    token = _create_token(user_id, "verify", ttl_hours=24)
    link = f"{_base_url()}/?verify={token}"
    send_email(
        email,
        "【入力保存アプリ】メールアドレスの確認",
        f"以下のリンクをクリックして登録を完了してください(24時間有効)。\n\n{link}",
    )
    audit.log_action(username, "signup", detail=email)
    return True, "確認メールを送信しました。メール内のリンクを開いて登録を完了してください。"


def verify_email(token):
    with _connect() as conn:
        row = conn.execute(
            "SELECT auth_tokens.*, users.username FROM auth_tokens "
            "JOIN users ON users.id = auth_tokens.user_id "
            "WHERE auth_tokens.token = %s AND auth_tokens.purpose = 'verify'",
            (token,),
        ).fetchone()
        if not row:
            return False, "無効なリンクです"
        if row["used_at"] is not None:
            return False, "このリンクは既に使用されています"
        if row["expires_at"] < datetime.now(timezone.utc):
            return False, "リンクの有効期限が切れています"

        conn.execute("UPDATE users SET is_verified = true WHERE id = %s", (row["user_id"],))
        conn.execute("UPDATE auth_tokens SET used_at = now() WHERE id = %s", (row["id"],))
    audit.log_action(row["username"], "email_verified")
    return True, "メールアドレスの確認が完了しました。ログインしてください。"


def authenticate(username, password):
    """成功: (userの辞書, None) / 失敗: (None, エラーメッセージ)"""
    if audit.recent_count(
        "login_failed", LOGIN_ATTEMPT_WINDOW_MINUTES, username=username
    ) >= LOGIN_ATTEMPT_LIMIT:
        return None, (
            f"ログイン試行回数が多すぎます。{LOGIN_ATTEMPT_WINDOW_MINUTES}分ほど時間をおいてから"
            "再度お試しください。"
        )

    user = get_user_by_username(username)
    if not user or not verify_password(password, user["password_hash"]):
        audit.log_action(username, "login_failed")
        return None, "ユーザー名またはパスワードが違います"
    if not user["is_verified"]:
        return None, "メールアドレスの確認がまだ完了していません。届いたメールをご確認ください。"
    audit.log_action(username, "login_success")
    return user, None


def request_password_reset(email):
    """メールが存在してもしなくても同じ文言を返す(メール存在の推測を防ぐ)。"""
    if audit.recent_count(
        "password_reset_requested", RESET_REQUEST_WINDOW_MINUTES, detail=email
    ) < RESET_REQUEST_LIMIT:
        user = get_user_by_email(email)
        if user:
            token = _create_token(user["id"], "reset", ttl_hours=1)
            link = f"{_base_url()}/?reset={token}"
            send_email(
                email,
                "【入力保存アプリ】パスワード再設定",
                f"以下のリンクから新しいパスワードを設定してください(1時間有効)。\n\n{link}",
            )
        audit.log_action(user["username"] if user else None, "password_reset_requested", detail=email)
    # 送信枠を使い切っていて実際には送っていない場合も、メール存在の推測を防ぐため文言は変えない
    return "このメールアドレス宛に、登録があれば再設定用のリンクを送信しました。"


def reset_password(token, new_password):
    with _connect() as conn:
        row = conn.execute(
            "SELECT auth_tokens.*, users.username FROM auth_tokens "
            "JOIN users ON users.id = auth_tokens.user_id "
            "WHERE auth_tokens.token = %s AND auth_tokens.purpose = 'reset'",
            (token,),
        ).fetchone()
        if not row:
            return False, "無効なリンクです"
        if row["used_at"] is not None:
            return False, "このリンクは既に使用されています"
        if row["expires_at"] < datetime.now(timezone.utc):
            return False, "リンクの有効期限が切れています"

        password_hash = hash_password(new_password)
        conn.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (password_hash, row["user_id"]),
        )
        conn.execute("UPDATE auth_tokens SET used_at = now() WHERE id = %s", (row["id"],))
    audit.log_action(row["username"], "password_reset_completed")
    return True, "パスワードを再設定しました。新しいパスワードでログインしてください。"


def admin_stats():
    with _connect() as conn:
        user_count = conn.execute("SELECT count(*) AS c FROM users").fetchone()["c"]
        memo_count = conn.execute("SELECT count(*) AS c FROM memos").fetchone()["c"]
    return {"user_count": user_count, "memo_count": memo_count}


def list_customers():
    """運営が顧客対応するための一覧。ユーザー名・メール・プラン・課金状態・登録日・保存件数を返す。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT u.username, u.email, u.plan, u.subscription_status, u.created_at, "
            "count(m.id) AS memo_count "
            "FROM users u LEFT JOIN memos m ON m.owner = u.username "
            "GROUP BY u.id "
            "ORDER BY u.created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]
