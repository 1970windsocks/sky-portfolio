import hashlib
import hmac
import json
import os

import psycopg
import pytest

import auth
import billing
import db
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


def create_user_with_api_token(username, email, password):
    """検証済みの一般ユーザーを作り、APIトークンを発行して返す。"""
    success, message = auth.create_user(username, email, password)
    assert success, message
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("UPDATE users SET is_verified = true WHERE username = %s", (username,))
    return auth.generate_api_token(username)


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


def test_api_memos_with_correct_token_returns_own_memos(client):
    token = create_user_with_api_token("api_tester", "api_tester@example.com", "pass1234")
    db.insert_memo("api_tester", "テストメモ", "テスト", "2026-09-18")

    response = client.get("/api/memos", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["owner"] == "api_tester"
    assert data["count"] == 1
    assert data["memos"][0]["text"] == "テストメモ"


def test_api_memos_without_token_returns_401(client):
    response = client.get("/api/memos")
    assert response.status_code == 401


def test_api_memos_with_wrong_token_returns_401(client):
    response = client.get("/api/memos", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_api_memos_cannot_read_another_users_memos_via_owner_param(client):
    """第54課題: IDORの再発防止。ownerパラメータを渡しても無視され、
    トークンの持ち主自身のメモしか返らないことを確認する。"""
    victim_token = create_user_with_api_token("victim", "victim@example.com", "pass1234")
    attacker_token = create_user_with_api_token("attacker", "attacker@example.com", "pass1234")
    db.insert_memo("victim", "被害者の秘密のメモ", "", "")

    # 攻撃者自身のトークンで、被害者のownerを指定してみる(以前はこれで覗けた)
    response = client.get(
        "/api/memos?owner=victim", headers={"Authorization": f"Bearer {attacker_token}"}
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["owner"] == "attacker"  # ownerパラメータは無視され、トークンの持ち主が優先される
    assert data["count"] == 0
    assert "被害者の秘密のメモ" not in json.dumps(data, ensure_ascii=False)

    # 被害者自身のトークンでなら、当然自分のメモは見える
    response = client.get("/api/memos", headers={"Authorization": f"Bearer {victim_token}"})
    assert response.get_json()["memos"][0]["text"] == "被害者の秘密のメモ"


def test_api_memos_rate_limit_returns_429_after_too_many_calls(client):
    """第48課題: 同じユーザーで短時間に叩きすぎると429で弾かれることを確認する。"""
    token = create_user_with_api_token("api_tester", "api_tester@example.com", "pass1234")
    other_token = create_user_with_api_token("other_user", "other_user@example.com", "pass1234")

    for _ in range(webhook_server.API_RATE_LIMIT):
        response = client.get("/api/memos", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200

    response = client.get("/api/memos", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 429

    # 別のユーザーはまだ制限に達していないので通る
    response = client.get("/api/memos", headers={"Authorization": f"Bearer {other_token}"})
    assert response.status_code == 200
