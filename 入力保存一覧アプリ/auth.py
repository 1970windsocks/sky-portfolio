import hashlib
import json
import os
import queue
import secrets
import threading
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


# 第60課題: 以前はsend_email()をサインアップ処理の中で直接呼んでおり、
# Resend APIへの実測約390msの往復が終わるまで「登録する」ボタンの応答が止まっていた。
# メール送信だけをキュー(順番待ちの箱)に積み、裏の専用スレッドで後から処理する形にして、
# 画面はすぐ返すようにする。
# 制約: プロセス内のキューなので、アプリが再起動/スリープすると積んだままの分は消える
# (RedisやSQSのような永続キューではない。今の無料プランの予算内でできる簡易版)。
_email_queue = queue.Queue()


def _email_worker():
    while True:
        to, subject, body = _email_queue.get()
        try:
            send_email(to, subject, body)
        except Exception as e:
            # バックグラウンドなので画面にはもう出せない。せめて記録だけは残す。
            audit.log_action(None, "email_send_failed", detail=f"{to}: {str(e)[:150]}")
        finally:
            _email_queue.task_done()


_email_worker_thread = threading.Thread(target=_email_worker, daemon=True)
_email_worker_thread.start()


def enqueue_email(to, subject, body):
    """send_email()を裏のキューに積む。呼び出し側はネットワーク往復を待たずに戻れる。"""
    _email_queue.put((to, subject, body))


def wait_for_pending_emails():
    """キューに積まれたメールが全部処理されるまで待つ(主にテスト用)。
    非同期化したことで、送信直後に結果を確認するテストが「まだ処理前」を
    掴んでしまうレースコンディションが起きるため、明示的に待つ手段を用意する。"""
    _email_queue.join()


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
    enqueue_email(
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
            enqueue_email(
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
    """運営が顧客対応するための一覧。ユーザー名・メール・プラン・課金状態・登録日・保存件数・ログイン回数を返す。

    memosとaudit_logはどちらもusersに対して1対多。両方を素朴にLEFT JOINしてから
    GROUP BYすると、行の掛け算(例: メモ3件×ログイン5件=15行)が起きて件数が水増しされる。
    それぞれを先に集計してから結合することで、この罠を避けている。
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT u.username, u.email, u.plan, u.subscription_status, u.created_at, "
            "COALESCE(m.memo_count, 0) AS memo_count, "
            "COALESCE(a.login_count, 0) AS login_count "
            "FROM users u "
            "LEFT JOIN (SELECT owner, count(*) AS memo_count FROM memos GROUP BY owner) m "
            "  ON m.owner = u.username "
            "LEFT JOIN (SELECT username, count(*) AS login_count FROM audit_log "
            "           WHERE action = 'login_success' GROUP BY username) a "
            "  ON a.username = u.username "
            "ORDER BY u.created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def _hash_api_token(token):
    # APIトークンはランダムな高エントロピー値(パスワードのような推測対象ではない)なので、
    # bcryptのような低速ハッシュは不要。SHA-256で十分(GitHubの個人アクセストークン等と同じ考え方)。
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_api_token(username):
    """このユーザー用のAPIトークンを新規発行する(第54課題)。

    戻り値は平文のトークン。これが見えるのはこの呼び出しの戻り値だけで、
    DBにはハッシュ値しか保存しない(パスワードと同じ考え方)。
    再発行すると古いトークンは即座に無効になる。
    """
    token = secrets.token_urlsafe(32)
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET api_token_hash = %s WHERE username = %s",
            (_hash_api_token(token), username),
        )
    return token


def get_user_by_api_token(token):
    """APIトークン(平文)から、それを発行したユーザーを1件だけ特定する。

    以前の実装は「合言葉が合っていればOK、誰のデータを見るかは呼び出し側の
    自己申告(ownerパラメータ)」だったため、トークンが1つ漏れると全ユーザーの
    データが読めてしまう権限設計の欠陥があった。今はトークン自体が
    「誰の代わりに動いているか」を一意に決める。
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE api_token_hash = %s", (_hash_api_token(token),)
        ).fetchone()
    return dict(row) if row else None
