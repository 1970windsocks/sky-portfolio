import base64
import json
import os
import urllib.parse
import urllib.request

import psycopg
from psycopg.rows import dict_row

FREE_MEMO_LIMIT = 5

API_BASE = "https://api.stripe.com/v1"


def _connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def _request(method, path, data=None):
    api_key = os.environ["STRIPE_SECRET_KEY"]
    body = urllib.parse.urlencode(data, doseq=True).encode("utf-8") if data else None

    request = urllib.request.Request(f"{API_BASE}{path}", data=body, method=method)
    auth = base64.b64encode(f"{api_key}:".encode()).decode()
    request.add_header("Authorization", f"Basic {auth}")
    request.add_header("User-Agent", "input-save-app/1.0")

    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def get_plan(username):
    with _connect() as conn:
        row = conn.execute(
            "SELECT plan FROM users WHERE username = %s", (username,)
        ).fetchone()
    return row["plan"] if row else "free"


def memo_count(username):
    with _connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS c FROM memos WHERE owner = %s", (username,)
        ).fetchone()
    return row["c"]


def create_checkout_session(username, base_url):
    price_id = os.environ["STRIPE_PRICE_ID"]
    data = {
        "mode": "subscription",
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "success_url": f"{base_url}/?checkout_success=1&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base_url}/?checkout_cancel=1",
        "client_reference_id": username,
    }
    session = _request("POST", "/checkout/sessions", data)
    return session["url"]


def confirm_checkout(session_id):
    """戻り値: (成功したか, メッセージ)。

    Stripeからのリダイレクトはブラウザの全画面遷移を伴うため、
    Streamlitのセッション状態(ログイン情報)が引き継がれているとは
    限らない。そのため、誰の決済かはセッション作成時に指定した
    client_reference_id(ユーザー名)をStripe側から取得して判定する。
    """
    session = _request("GET", f"/checkout/sessions/{session_id}")

    username = session.get("client_reference_id")
    if not username:
        return False, "この決済に対応するアカウントが見つかりません"
    if session.get("payment_status") != "paid":
        return False, "決済が完了していません"

    with _connect() as conn:
        conn.execute(
            "UPDATE users SET plan = 'pro', stripe_customer_id = %s, stripe_subscription_id = %s WHERE username = %s",
            (session.get("customer"), session.get("subscription"), username),
        )
    return True, "Proプランへのアップグレードが完了しました🎉 もう一度ログインしてください。"
