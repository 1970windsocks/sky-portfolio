import base64
import hashlib
import hmac
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


def get_subscription_status(username):
    with _connect() as conn:
        row = conn.execute(
            "SELECT subscription_status FROM users WHERE username = %s", (username,)
        ).fetchone()
    return row["subscription_status"] if row else "none"


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


def verify_stripe_signature(payload, sig_header, secret):
    """Stripe-Signatureヘッダを検証する。

    payload: リクエストボディの生バイト列(json.loadsする前のもの)。
    sig_header: `Stripe-Signature`ヘッダの値(例: "t=169...,v1=abcdef...")。
    secret: Stripeのwebhook署名シークレット(whsec_...)。

    戻り値: 検証に成功した場合はパース済みのイベント(dict)、失敗した場合はNone。
    """
    try:
        pairs = dict(item.split("=", 1) for item in sig_header.split(","))
        timestamp = pairs["t"]
        signature = pairs["v1"]
    except (KeyError, ValueError, AttributeError):
        return None

    signed_payload = f"{timestamp}.".encode("utf-8") + payload
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None

    return json.loads(payload)


def _update_by_customer(customer_id, plan=None, subscription_status=None):
    if not customer_id:
        return
    sets, params = [], []
    if plan is not None:
        sets.append("plan = %s")
        params.append(plan)
    if subscription_status is not None:
        sets.append("subscription_status = %s")
        params.append(subscription_status)
    if not sets:
        return
    params.append(customer_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE users SET {', '.join(sets)} WHERE stripe_customer_id = %s",
            params,
        )


def apply_subscription_event(event):
    """検証済みのStripeイベントを受け取り、ユーザーの状態に反映する。"""
    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})
    customer_id = data.get("customer")

    if event_type == "invoice.payment_succeeded":
        _update_by_customer(customer_id, plan="pro", subscription_status="active")
    elif event_type == "invoice.payment_failed":
        # すぐには止めない: プランはproのまま維持し、状態だけpast_dueにして猶予を与える
        _update_by_customer(customer_id, subscription_status="past_due")
    elif event_type == "customer.subscription.deleted":
        _update_by_customer(customer_id, plan="free", subscription_status="canceled")


def cancel_subscription(username):
    """戻り値: (成功したか, メッセージ)。Stripe側を解約し、DBも即時Freeに戻す。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT stripe_subscription_id FROM users WHERE username = %s", (username,)
        ).fetchone()
    subscription_id = row["stripe_subscription_id"] if row else None
    if not subscription_id:
        return False, "有効なサブスクリプションが見つかりません"

    _request("DELETE", f"/subscriptions/{subscription_id}")

    with _connect() as conn:
        conn.execute(
            "UPDATE users SET plan = 'free', subscription_status = 'canceled' WHERE username = %s",
            (username,),
        )
    return True, "解約しました。プランはFreeに戻りました。"
