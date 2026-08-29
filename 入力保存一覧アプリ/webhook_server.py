import os

from flask import Flask, request

import billing
import migrate

app = Flask(__name__)

migrate.run_pending_migrations(os.environ["DATABASE_URL"])


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    secret = os.environ["STRIPE_WEBHOOK_SECRET"]

    event = billing.verify_stripe_signature(payload, sig_header, secret)
    if event is None:
        return "invalid signature", 400

    billing.apply_subscription_event(event)
    return "ok", 200


@app.route("/healthz", methods=["GET"])
def healthz():
    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
