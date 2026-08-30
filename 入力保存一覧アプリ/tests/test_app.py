import os
import sys
from pathlib import Path

import psycopg
from streamlit.testing.v1 import AppTest

APP_DIR = Path(__file__).resolve().parent.parent
APP_PATH = str(APP_DIR / "app.py")

sys.path.insert(0, str(APP_DIR))
import audit  # noqa: E402
import auth  # noqa: E402
import billing  # noqa: E402
import db  # noqa: E402


def set_plan(username, plan):
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("UPDATE users SET plan = %s WHERE username = %s", (plan, username))


def create_verified_user(username, email, password, role="user"):
    success, message = auth.create_user(username, email, password)
    assert success, message
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute(
            "UPDATE users SET is_verified = true, role = %s WHERE username = %s",
            (role, username),
        )


def make_app():
    return AppTest.from_file(APP_PATH, default_timeout=15)


def login(at, username, password):
    at.run()
    at.text_input(key="login_username").input(username)
    at.text_input(key="login_password").input(password)
    [b for b in at.button if b.label == "ログイン"][0].click().run()


def extract_link(sent_emails, marker):
    body = sent_emails[-1]["body"]
    for line in body.splitlines():
        if marker in line:
            return line.strip()
    return body.strip().splitlines()[-1]


def test_signup_then_login_blocked_until_verified(no_real_email):
    at = make_app()
    at.run()

    at.text_input(key="signup_username").input("newuser")
    at.text_input(key="signup_email").input("newuser@example.com")
    at.text_input(key="signup_password").input("password123")
    [b for b in at.button if b.label == "登録する"][0].click().run()

    assert any("確認メール" in s.value for s in at.success)
    assert len(no_real_email) == 1
    assert no_real_email[0]["to"] == "newuser@example.com"

    # 確認前はログインできない
    login(at, "newuser", "password123")
    assert any("確認がまだ完了していません" in e.value for e in at.error)


def test_verify_link_then_login_succeeds(no_real_email):
    at = make_app()
    at.run()
    at.text_input(key="signup_username").input("newuser")
    at.text_input(key="signup_email").input("newuser@example.com")
    at.text_input(key="signup_password").input("password123")
    [b for b in at.button if b.label == "登録する"][0].click().run()

    link = extract_link(no_real_email, "?verify=")
    token = link.split("?verify=")[1]

    at2 = make_app()
    at2.query_params["verify"] = token
    at2.run()
    assert any("確認が完了しました" in s.value for s in at2.success)

    login(at2, "newuser", "password123")
    assert at2.session_state["username"] == "newuser"


def test_wrong_password_shows_error():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()
    login(at, "tester", "wrongpass")

    assert any("違います" in e.value for e in at.error)
    assert at.session_state["username"] is None


def test_password_reset_flow(no_real_email):
    create_verified_user("tester", "tester@example.com", "oldpass123")

    at = make_app()
    at.run()
    with_expander = at.text_input(key="forgot_email")
    with_expander.input("tester@example.com")
    [b for b in at.button if b.label == "再設定メールを送る"][0].click().run()

    link = extract_link(no_real_email, "?reset=")
    token = link.split("?reset=")[1]

    at2 = make_app()
    at2.query_params["reset"] = token
    at2.run()
    at2.text_input(key="reset_password").input("newpass456")
    at2.text_input(key="reset_password_confirm").input("newpass456")
    [b for b in at2.button if b.label == "パスワードを再設定する"][0].click().run()

    login(at2, "tester", "oldpass123")
    assert any("違います" in e.value for e in at2.error)

    at3 = make_app()
    login(at3, "tester", "newpass456")
    assert at3.session_state["username"] == "tester"


def test_login_then_save_item_appears_in_list():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()
    login(at, "tester", "pass1234")
    assert at.session_state["username"] == "tester"

    at.text_input[0].input("牛乳を買う")
    [b for b in at.button if b.label == "保存"][0].click().run()
    assert any("牛乳を買う" in s.value for s in at.success)

    at.run()  # 保存後、次の再描画で一覧に反映される
    assert any("牛乳を買う" in m.value for m in at.markdown)
    assert any("現在 1 件保存されています" in c.value for c in at.caption)


def test_empty_text_shows_warning():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()
    login(at, "tester", "pass1234")

    at.text_input[0].input("   ")
    [b for b in at.button if b.label == "保存"][0].click().run()

    assert any("何か入力してください" in w.value for w in at.warning)


def test_cross_tenant_isolation():
    """顧客Aで保存したデータが、顧客Bには絶対に見えないことを確認する。"""
    create_verified_user("tenant_a", "a@example.com", "passA1234")
    create_verified_user("tenant_b", "b@example.com", "passB1234")

    at = make_app()
    login(at, "tenant_a", "passA1234")
    at.text_input[0].input("Aだけの秘密メモ")
    [b for b in at.button if b.label == "保存"][0].click().run()
    at.run()
    assert any("Aだけの秘密メモ" in m.value for m in at.markdown)

    [b for b in at.button if b.label == "ログアウト"][0].click().run()
    assert at.session_state["username"] is None

    login(at, "tenant_b", "passB1234")
    assert at.session_state["username"] == "tenant_b"

    visible_text = " ".join(m.value for m in at.markdown)
    assert "Aだけの秘密メモ" not in visible_text
    assert any("現在 0 件保存されています" in c.value for c in at.caption)


def test_toggle_favorite():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()
    login(at, "tester", "pass1234")

    at.text_input[0].input("牛乳を買う")
    [b for b in at.button if b.label == "保存"][0].click().run()
    at.run()

    fav_button = [b for b in at.button if b.key and b.key.startswith("fav_")][0]
    assert fav_button.label == "☆"

    fav_button.click().run()
    fav_button = [b for b in at.button if b.key and b.key.startswith("fav_")][0]
    assert fav_button.label == "⭐"


def test_free_plan_blocks_at_limit():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()
    login(at, "tester", "pass1234")

    for i in range(billing.FREE_MEMO_LIMIT):
        at.text_input[0].input(f"メモ{i}")
        [b for b in at.button if b.label == "保存"][0].click().run()
        at.run()

    assert any(f"現在 {billing.FREE_MEMO_LIMIT} 件保存されています" in c.value for c in at.caption)

    at.text_input[0].input("上限を超える1件")
    [b for b in at.button if b.label == "保存"][0].click().run()

    assert any("Freeプランは" in w.value and "までです" in w.value for w in at.warning)
    # アップグレード用のリンクが作られている(Stripeへの実接続はモック済み)
    assert "checkout_url" in at.session_state
    assert at.session_state["checkout_url"].startswith("https://stripe.example/")


def test_checkout_success_upgrades_plan(no_real_stripe):
    create_verified_user("tester", "tester@example.com", "pass1234")

    at = make_app()
    login(at, "tester", "pass1234")
    for i in range(billing.FREE_MEMO_LIMIT):
        at.text_input[0].input(f"メモ{i}")
        [b for b in at.button if b.label == "保存"][0].click().run()
        at.run()
    # 「アップグレード」導線を出させ、Checkout Sessionを作らせる
    at.text_input[0].input("もう1件")
    [b for b in at.button if b.label == "保存"][0].click().run()
    session_id = at.session_state["checkout_url"].rsplit("/", 1)[-1]

    # Stripe上で支払いが完了した状態を模擬する
    no_real_stripe[session_id]["payment_status"] = "paid"

    at2 = make_app()
    at2.query_params["checkout_success"] = "1"
    at2.query_params["session_id"] = session_id
    at2.run()
    assert any("アップグレードが完了しました" in s.value for s in at2.success)

    assert billing.get_plan("tester") == "pro"


def test_pro_plan_has_no_limit():
    create_verified_user("tester", "tester@example.com", "pass1234")
    set_plan("tester", "pro")

    at = make_app()
    login(at, "tester", "pass1234")

    for i in range(billing.FREE_MEMO_LIMIT + 2):
        at.text_input[0].input(f"メモ{i}")
        [b for b in at.button if b.label == "保存"][0].click().run()
        at.run()

    assert any(
        f"現在 {billing.FREE_MEMO_LIMIT + 2} 件保存されています" in c.value for c in at.caption
    )
    assert not any("Freeプランは" in w.value for w in at.warning)


def test_admin_dashboard_visible_only_to_admin():
    create_verified_user("bosssan", "boss@example.com", "pass1234", role="admin")
    create_verified_user("staffsan", "staff@example.com", "pass1234", role="user")

    at_admin = make_app()
    login(at_admin, "bosssan", "pass1234")
    assert any("管理者ダッシュボード" in e.label for e in at_admin.expander)

    at_user = make_app()
    login(at_user, "staffsan", "pass1234")
    assert not any("管理者ダッシュボード" in e.label for e in at_user.expander)


def test_free_plan_csv_export_is_locked():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()
    login(at, "tester", "pass1234")

    assert any("CSVエクスポートはProプラン限定" in c.value for c in at.caption)


def test_pro_plan_csv_export_is_not_locked():
    create_verified_user("tester", "tester@example.com", "pass1234")
    set_plan("tester", "pro")
    at = make_app()
    login(at, "tester", "pass1234")

    assert not any("CSVエクスポートはProプラン限定" in c.value for c in at.caption)


def test_monthly_plan_caption_shows_month_wording():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()
    login(at, "tester", "pass1234")

    assert any("Free(月" in c.value and "今月" in c.value for c in at.caption)


def test_save_with_category_shows_metadata():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()
    login(at, "tester", "pass1234")

    at.text_input[0].input("会議メモ")
    at.text_input[1].input("仕事")
    [b for b in at.button if b.label == "保存"][0].click().run()
    at.run()  # 保存後、次の再描画で一覧に反映される

    assert any("会議メモ" in m.value for m in at.markdown)
    assert any("🏷️ 仕事" in c.value for c in at.caption)
    assert any("📅 " in c.value for c in at.caption)


def test_search_filters_list():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()
    login(at, "tester", "pass1234")

    at.text_input[0].input("牛乳を買う")
    [b for b in at.button if b.label == "保存"][0].click().run()
    at.text_input[0].input("本を読む")
    [b for b in at.button if b.label == "保存"][0].click().run()

    at.text_input(key="search_query").input("牛乳").run()

    visible_text = " ".join(m.value for m in at.markdown)
    assert "牛乳を買う" in visible_text
    assert "本を読む" not in visible_text


def test_category_filter_narrows_list():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()
    login(at, "tester", "pass1234")

    at.text_input[0].input("会議メモ")
    at.text_input[1].input("仕事")
    [b for b in at.button if b.label == "保存"][0].click().run()
    at.run()  # 保存後、次の再描画で一覧に反映される
    at.text_input[0].input("旅行のアイデア")
    at.text_input[1].input("プライベート")
    [b for b in at.button if b.label == "保存"][0].click().run()
    at.run()  # 保存後、次の再描画で一覧に反映される

    at.selectbox(key="category_filter").select("仕事").run()

    visible_text = " ".join(m.value for m in at.markdown)
    assert "会議メモ" in visible_text
    assert "旅行のアイデア" not in visible_text


def test_sort_order_changes_display_order():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()
    login(at, "tester", "pass1234")

    at.text_input[0].input("最初のメモ")
    [b for b in at.button if b.label == "保存"][0].click().run()
    at.run()  # 保存後、次の再描画で一覧に反映される
    at.text_input[0].input("次のメモ")
    [b for b in at.button if b.label == "保存"][0].click().run()
    at.run()  # 保存後、次の再描画で一覧に反映される

    # デフォルトは「新しい順」: 後から保存したものが先に表示される
    texts_newest_first = [m.value for m in at.markdown]
    assert texts_newest_first.index("次のメモ") < texts_newest_first.index("最初のメモ")

    at.radio(key="sort_order").set_value("古い順").run()
    texts_oldest_first = [m.value for m in at.markdown]
    assert texts_oldest_first.index("最初のメモ") < texts_oldest_first.index("次のメモ")


def test_text_length_limit_shows_error():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()
    login(at, "tester", "pass1234")

    at.text_input[0].input("あ" * 2001)  # app.py の MAX_TEXT_LENGTH(2000)を超える長さ
    [b for b in at.button if b.label == "保存"][0].click().run()

    assert any("内容が長すぎます" in e.value for e in at.error)


def test_category_length_limit_shows_error():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()
    login(at, "tester", "pass1234")

    at.text_input[0].input("普通のメモ")
    at.text_input[1].input("あ" * 51)
    [b for b in at.button if b.label == "保存"][0].click().run()

    assert any("カテゴリーが長すぎます" in e.value for e in at.error)


def test_cross_tenant_cannot_mutate_via_direct_id():
    """他人のメモIDを直接指定しても更新・削除・お気に入り切替ができないことを確認する(テナント越境ゼロの再確認)。"""
    create_verified_user("tenant_a", "a2@example.com", "passA1234")
    create_verified_user("tenant_b", "b2@example.com", "passB1234")

    db.insert_memo("tenant_a", "Aだけの秘密メモ")
    memo_id = db.list_memos("tenant_a")[0]["id"]

    # Bが直接IDを指定しても、DB層のowner検証で無視される
    db.update_memo(memo_id, "tenant_b", "書き換えました")
    db.delete_memo(memo_id, "tenant_b")
    db.set_favorite(memo_id, "tenant_b", True)

    remaining = db.list_memos("tenant_a")
    assert len(remaining) == 1
    assert remaining[0]["text"] == "Aだけの秘密メモ"
    assert remaining[0]["is_favorite"] is False


def test_login_locks_out_after_repeated_failures():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()

    for _ in range(5):
        login(at, "tester", "wrongpass")
        assert any("違います" in e.value for e in at.error)

    # 直近の失敗が多すぎるため、正しいパスワードでもロックアウトされる
    login(at, "tester", "pass1234")
    assert any("試行回数が多すぎます" in e.value for e in at.error)
    assert at.session_state["username"] is None


def test_signup_and_login_are_logged(no_real_email):
    at = make_app()
    at.run()
    at.text_input(key="signup_username").input("newuser")
    at.text_input(key="signup_email").input("newuser@example.com")
    at.text_input(key="signup_password").input("password123")
    [b for b in at.button if b.label == "登録する"][0].click().run()

    entries = audit.recent_entries()
    assert any(e["action"] == "signup" and e["username"] == "newuser" for e in entries)

    link = extract_link(no_real_email, "?verify=")
    token = link.split("?verify=")[1]
    at2 = make_app()
    at2.query_params["verify"] = token
    at2.run()

    login(at2, "newuser", "password123")
    assert at2.session_state["username"] == "newuser"

    entries = audit.recent_entries()
    assert any(e["action"] == "login_success" and e["username"] == "newuser" for e in entries)


def test_password_reset_rate_limited_after_repeated_requests(no_real_email):
    create_verified_user("tester", "tester@example.com", "oldpass123")
    # create_verified_user自体が確認メールを1通送っているので、ここが起点の件数になる
    sent_before_reset_requests = len(no_real_email)

    at = make_app()
    at.run()

    for _ in range(3):
        at.text_input(key="forgot_email").input("tester@example.com")
        [b for b in at.button if b.label == "再設定メールを送る"][0].click().run()

    assert len(no_real_email) == sent_before_reset_requests + 3  # 3回までは送られる

    at.text_input(key="forgot_email").input("tester@example.com")
    [b for b in at.button if b.label == "再設定メールを送る"][0].click().run()

    # 4回目は送信枠を超えたため、実際には送られない(文言は変わらない)
    assert len(no_real_email) == sent_before_reset_requests + 3


def test_onboarding_message_shown_until_first_save():
    create_verified_user("tester", "tester@example.com", "pass1234")
    at = make_app()
    login(at, "tester", "pass1234")

    assert any("はじめての方へ" in i.value for i in at.info)

    at.text_input[0].input("最初のメモ")
    [b for b in at.button if b.label == "保存"][0].click().run()
    at.run()  # 保存後、次の再描画で一覧に反映される

    assert not any("はじめての方へ" in i.value for i in at.info)


def test_admin_dashboard_shows_customer_list(monkeypatch):
    import ops

    monkeypatch.setattr(ops, "uptime_summary", lambda: None)

    create_verified_user("bosssan", "boss@example.com", "pass1234", role="admin")
    create_verified_user("staffsan", "staff@example.com", "pass1234", role="user")

    at = make_app()
    login(at, "bosssan", "pass1234")

    table_text = " ".join(str(df.value) for df in at.dataframe)
    assert "bosssan" in table_text
    assert "staffsan" in table_text
