import os

from flask import Flask, jsonify, request

import audit
import auth
import billing
import db
import migrate

app = Flask(__name__)

migrate.run_pending_migrations(os.environ["DATABASE_URL"])

API_RATE_LIMIT = 30  # 1分あたりの呼び出し上限(ユーザーごと)
API_RATE_WINDOW_MINUTES = 1


def _authenticated_user():
    """Authorizationヘッダの Bearer トークンから、それを発行したユーザーを特定する。

    第54課題で修正した点: 以前は全員が同じ合言葉(環境変数API_TOKEN)を使い、
    「誰のデータを見るか」はクライアントが送るownerパラメータの自己申告に
    任されていた。トークンが1つ漏れるだけで全ユーザーのメモが読める、
    権限設計上の欠陥(IDOR)だった。今はユーザーごとに別のトークンを発行し、
    トークン自体が「誰の代わりに動いているか」を決める。
    """
    header = request.headers.get("Authorization", "")
    token = header[len("Bearer "):] if header.startswith("Bearer ") else None
    if not token:
        return None
    return auth.get_user_by_api_token(token)


@app.route("/api/memos", methods=["GET"])
def api_memos():
    """保存しているメモをJSONで返す外部向けAPI(第47課題、第54課題で権限設計を修正)。

    使い方: GET /api/memos
    ヘッダ: Authorization: Bearer <そのユーザー自身のAPIトークン>

    誰のメモを返すかはトークンの持ち主で決まり、ownerパラメータでの指定は廃止した。
    トークンが漏れた場合や呼び出し元のバグで連打されても本番DBに過剰な負荷を
    かけないよう、ユーザーごとに1分間の呼び出し回数を制限する(第48課題)。
    """
    user = _authenticated_user()
    if user is None:
        return jsonify({"error": "認証に失敗しました(トークンが無いか誤っています)"}), 401

    owner = user["username"]

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
