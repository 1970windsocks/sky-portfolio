import os
import sys
from pathlib import Path

import psycopg
from streamlit.testing.v1 import AppTest

APP_DIR = Path(__file__).resolve().parent.parent
APP_PATH = str(APP_DIR / "app.py")

sys.path.insert(0, str(APP_DIR))
import auth  # noqa: E402
import billing  # noqa: E402


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
