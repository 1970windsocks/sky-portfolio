import hashlib
import hmac
import json
import os

import psycopg

import auth
import billing

SECRET = "whsec_test_secret"


def create_verified_user(username, email, password, plan="pro", customer_id="cus_test_1", subscription_id="sub_test_1"):
    success, message = auth.create_user(username, email, password)
    assert success, message
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute(
            "UPDATE users SET is_verified = true, plan = %s, stripe_customer_id = %s, "
            "stripe_subscription_id = %s WHERE username = %s",
            (plan, customer_id, subscription_id, username),
        )


def sign(payload_bytes, timestamp, secret=SECRET):
    signed_payload = f"{timestamp}.".encode("utf-8") + payload_bytes
    signature = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def make_event(event_type, customer_id="cus_test_1"):
    return json.dumps(
        {
            "type": event_type,
            "data": {"object": {"customer": customer_id}},
        }
    ).encode("utf-8")


def test_verify_stripe_signature_accepts_valid_signature():
    payload = make_event("invoice.payment_succeeded")
    sig_header = sign(payload, timestamp="1700000000")

    event = billing.verify_stripe_signature(payload, sig_header, SECRET)

    assert event is not None
    assert event["type"] == "invoice.payment_succeeded"


def test_verify_stripe_signature_rejects_tampered_payload():
    payload = make_event("invoice.payment_succeeded")
    sig_header = sign(payload, timestamp="1700000000")

    tampered = make_event("customer.subscription.deleted")
    event = billing.verify_stripe_signature(tampered, sig_header, SECRET)

    assert event is None


def test_verify_stripe_signature_rejects_wrong_secret():
    payload = make_event("invoice.payment_succeeded")
    sig_header = sign(payload, timestamp="1700000000", secret="whsec_other_secret")

    event = billing.verify_stripe_signature(payload, sig_header, SECRET)

    assert event is None


def test_verify_stripe_signature_rejects_malformed_header():
    payload = make_event("invoice.payment_succeeded")

    assert billing.verify_stripe_signature(payload, "not-a-valid-header", SECRET) is None
    assert billing.verify_stripe_signature(payload, "", SECRET) is None


def test_apply_subscription_event_payment_succeeded_sets_active_pro():
    create_verified_user("tester", "tester@example.com", "pass1234", plan="free")
    event = json.loads(make_event("invoice.payment_succeeded"))

    billing.apply_subscription_event(event)

    assert billing.get_plan("tester") == "pro"
    assert billing.get_subscription_status("tester") == "active"


def test_apply_subscription_event_payment_failed_keeps_pro_but_marks_past_due():
    create_verified_user("tester", "tester@example.com", "pass1234", plan="pro")
    event = json.loads(make_event("invoice.payment_failed"))

    billing.apply_subscription_event(event)

    # 支払い失敗直後はすぐに止めない(猶予): planはproのまま維持される
    assert billing.get_plan("tester") == "pro"
    assert billing.get_subscription_status("tester") == "past_due"


def test_apply_subscription_event_subscription_deleted_sets_free_canceled():
    create_verified_user("tester", "tester@example.com", "pass1234", plan="pro")
    event = json.loads(make_event("customer.subscription.deleted"))

    billing.apply_subscription_event(event)

    assert billing.get_plan("tester") == "free"
    assert billing.get_subscription_status("tester") == "canceled"


def test_apply_subscription_event_unknown_customer_is_ignored():
    create_verified_user("tester", "tester@example.com", "pass1234", plan="pro")
    event = json.loads(make_event("customer.subscription.deleted", customer_id="cus_unknown"))

    billing.apply_subscription_event(event)

    # どのユーザーにも紐付かないので、既存ユーザーの状態は変わらない
    assert billing.get_plan("tester") == "pro"


def test_cancel_subscription_calls_stripe_and_downgrades_to_free(no_real_stripe):
    create_verified_user("tester", "tester@example.com", "pass1234", plan="pro", subscription_id="sub_abc")

    success, message = billing.cancel_subscription("tester")

    assert success, message
    assert billing.get_plan("tester") == "free"
    assert billing.get_subscription_status("tester") == "canceled"


def test_cancel_subscription_without_active_subscription_fails():
    create_verified_user("tester", "tester@example.com", "pass1234", plan="free", subscription_id=None)

    success, message = billing.cancel_subscription("tester")

    assert not success
