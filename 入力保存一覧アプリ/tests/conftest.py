import os
import sys
from pathlib import Path

import psycopg
import pytest

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import auth  # noqa: E402
import billing  # noqa: E402
import migrate  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    database_url = os.environ["DATABASE_URL"]
    migrate.run_pending_migrations(database_url)
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("TRUNCATE memos RESTART IDENTITY")
        conn.execute("TRUNCATE auth_tokens, users RESTART IDENTITY CASCADE")
        # 監査ログが残っているとレート制限(直近N分の件数)の判定がテスト間で汚染されるため必ず消す
        conn.execute("TRUNCATE audit_log RESTART IDENTITY")
    yield


@pytest.fixture(autouse=True)
def no_real_email(monkeypatch):
    """テストでは実際にメールを送らず、送信内容だけを記録する。"""
    sent = []

    def fake_send_email(to, subject, body):
        sent.append({"to": to, "subject": subject, "body": body})

    monkeypatch.setattr(auth, "send_email", fake_send_email)
    return sent


@pytest.fixture(autouse=True)
def no_real_stripe(monkeypatch):
    """テストでは実際にStripeへ接続せず、セッションをメモリ上で模擬する。"""
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_dummy")
    sessions = {}
    subscriptions_canceled = []

    def fake_request(method, path, data=None):
        if method == "POST" and path == "/checkout/sessions":
            session_id = f"cs_test_{len(sessions) + 1}"
            sessions[session_id] = {
                "id": session_id,
                "url": f"https://stripe.example/checkout/{session_id}",
                "client_reference_id": data.get("client_reference_id"),
                "payment_status": "unpaid",
                "customer": "cus_test_1",
                "subscription": "sub_test_1",
            }
            return sessions[session_id]
        if method == "GET" and path.startswith("/checkout/sessions/"):
            session_id = path.rsplit("/", 1)[-1]
            return sessions.get(session_id, {"payment_status": "unpaid"})
        if method == "DELETE" and path.startswith("/subscriptions/"):
            subscription_id = path.rsplit("/", 1)[-1]
            subscriptions_canceled.append(subscription_id)
            return {"id": subscription_id, "status": "canceled"}
        raise AssertionError(f"unexpected stripe call: {method} {path}")

    monkeypatch.setattr(billing, "_request", fake_request)
    fake_request.sessions = sessions
    fake_request.subscriptions_canceled = subscriptions_canceled
    return sessions
