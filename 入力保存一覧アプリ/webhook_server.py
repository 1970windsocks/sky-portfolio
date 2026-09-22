import os

from flask import Flask, jsonify, request

import audit
import billing
import db
import migrate

app = Flask(__name__)

migrate.run_pending_migrations(os.environ["DATABASE_URL"])

API_RATE_LIMIT = 30  # 1分あたりの呼び出し上限(ownerごと)
API_RATE_WINDOW_MINUTES = 1


def _check_api_token():
    """Authorizationヘッダの Bearer トークンを、環境変数API_TOKEN(合鍵)と照合する。"""
    expected = os.environ.get("API_TOKEN")
    header = request.headers.get("Authorization", "")
    provided = header[len("Bearer "):] if header.startswith("Bearer ") else None
    return bool(expected) and provided == expected


@app.route("/api/memos", methods=["GET"])
def api_memos():
    """保存しているメモをJSONで返す外部向けAPI(第47課題)。

    使い方: GET /api/memos?owner=<ユーザー名>
    ヘッダ: Authorization: Bearer <API_TOKENの値>

    トークンが漏れた場合や呼び出し元のバグで連打されても本番DBに
    過剰な負荷をかけないよう、ownerごとに1分間の呼び出し回数を制限する(第48課題)。
    """
    if not _check_api_token():
        return jsonify({"error": "認証に失敗しました(トークンが無いか誤っています)"}), 401

    owner = request.args.get("owner", "")
    if not owner:
        return jsonify({"error": "ownerパラメータが必要です"}), 400

    if audit.recent_count("api_memos_call", API_RATE_WINDOW_MINUTES, username=owner) >= API_RATE_LIMIT:
        return jsonify(
            {"error": f"呼び出しが多すぎます。{API_RATE_WINDOW_MINUTES}分ほど時間をおいてください。"}
        ), 429

    audit.log_action(owner, "api_memos_call")
    memos = db.list_memos(owner)
    return jsonify({"owner": owner, "count": len(memos), "memos": memos}), 200


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
