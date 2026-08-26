from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


def make_app(monkeypatch, tmp_path):
    # data.json は相対パスで開かれるので、実データを壊さないよう
    # 一時フォルダに移動してからアプリを起動する
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(APP_PATH, default_timeout=15)
    at.secrets["users"] = {"tester": "pass123"}
    return at


def login(at, username="tester", password="pass123"):
    at.run()
    at.text_input[0].input(username)
    at.text_input[1].input(password)
    at.button[0].click().run()


def test_wrong_password_shows_error(monkeypatch, tmp_path):
    at = make_app(monkeypatch, tmp_path)
    login(at, "tester", "wrongpass")

    assert any("違います" in e.value for e in at.error)
    assert at.session_state["username"] is None


def test_login_then_save_item_appears_in_list(monkeypatch, tmp_path):
    at = make_app(monkeypatch, tmp_path)
    login(at)
    assert at.session_state["username"] == "tester"

    at.text_input[0].input("牛乳を買う")
    [b for b in at.button if b.label == "保存"][0].click().run()
    assert any("牛乳を買う" in s.value for s in at.success)

    at.run()  # 保存後、次の再描画で一覧に反映される
    assert any("牛乳を買う" in m.value for m in at.markdown)
    assert any("現在 1 件保存されています" in c.value for c in at.caption)


def test_empty_text_shows_warning(monkeypatch, tmp_path):
    at = make_app(monkeypatch, tmp_path)
    login(at)

    at.text_input[0].input("   ")
    [b for b in at.button if b.label == "保存"][0].click().run()

    assert any("何か入力してください" in w.value for w in at.warning)
