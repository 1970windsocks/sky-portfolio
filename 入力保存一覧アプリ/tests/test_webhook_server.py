import hashlib
import hmac
import json
import os

import psycopg
import pytest

import auth
import billing
import webhook_server

SECRET = "whsec_test_secret"


@pytest.fixture(autouse=True)
def webhook_secret(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)


@pytest.fixture
def client():
    webhook_server.app.testing = True
    return webhook_server.app.test_client()


def create_pro_user(username, email, password, customer_id="cus_test_1"):
    success, message = auth.create_user(username, email, password)
    assert success, message
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute(
            "UPDATE users SET is_verified = true, plan = 'pro', stripe_customer_id = %s WHERE username = %s",
            (customer_id, username),
        )


def sign(payload_bytes, timestamp="1700000000", secret=SECRET):
    signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
    signature = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def test_webhook_with_valid_signature_returns_200_and_updates_db(client):
    create_pro_user("tester", "tester@example.com", "pass1234")
    payload = json.dumps(
        {"type": "customer.subscription.deleted", "data": {"object": {"customer": "cus_test_1"}}}
    ).encode("utf-8")

    response = client.post(
        "/stripe/webhook",
        data=payload,
        headers={"Stripe-Signature": sign(payload), "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert billing.get_plan("tester") == "free"
    assert billing.get_subscription_status("tester") == "canceled"


def test_webhook_with_invalid_signature_returns_400_and_does_not_update_db(client):
    create_pro_user("tester", "tester@example.com", "pass1234")
    payload = json.dumps(
        {"type": "customer.subscription.deleted", "data": {"object": {"customer": "cus_test_1"}}}
    ).encode("utf-8")

    response = client.post(
        "/stripe/webhook",
        data=payload,
        headers={"Stripe-Signature": "t=1700000000,v1=deadbeef", "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert billing.get_plan("tester") == "pro"


def test_webhook_missing_signature_header_returns_400(client):
    payload = json.dumps({"type": "invoice.payment_succeeded", "data": {"object": {}}}).encode("utf-8")

    response = client.post("/stripe/webhook", data=payload, headers={"Content-Type": "application/json"})

    assert response.status_code == 400


def test_healthz_returns_200(client):
    response = client.get("/healthz")
    assert response.status_code == 200
