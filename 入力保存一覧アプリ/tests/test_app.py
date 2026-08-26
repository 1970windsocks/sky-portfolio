import os
import sys
from pathlib import Path

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

APP_DIR = Path(__file__).resolve().parent.parent
APP_PATH = str(APP_DIR / "app.py")

sys.path.insert(0, str(APP_DIR))
import migrate  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    database_url = os.environ["DATABASE_URL"]
    migrate.run_pending_migrations(database_url)
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("TRUNCATE memos RESTART IDENTITY")
    yield


def make_app():
    at = AppTest.from_file(APP_PATH, default_timeout=15)
    at.secrets["users"] = {"tester": "pass123"}
    return at


def login(at, username="tester", password="pass123"):
    at.run()
    at.text_input[0].input(username)
    at.text_input[1].input(password)
    at.button[0].click().run()


def test_wrong_password_shows_error():
    at = make_app()
    login(at, "tester", "wrongpass")

    assert any("違います" in e.value for e in at.error)
    assert at.session_state["username"] is None


def test_login_then_save_item_appears_in_list():
    at = make_app()
    login(at)
    assert at.session_state["username"] == "tester"

    at.text_input[0].input("牛乳を買う")
    [b for b in at.button if b.label == "保存"][0].click().run()
    assert any("牛乳を買う" in s.value for s in at.success)

    at.run()  # 保存後、次の再描画で一覧に反映される
    assert any("牛乳を買う" in m.value for m in at.markdown)
    assert any("現在 1 件保存されています" in c.value for c in at.caption)


def test_empty_text_shows_warning():
    at = make_app()
    login(at)

    at.text_input[0].input("   ")
    [b for b in at.button if b.label == "保存"][0].click().run()

    assert any("何か入力してください" in w.value for w in at.warning)


def test_toggle_favorite():
    at = make_app()
    login(at)

    at.text_input[0].input("牛乳を買う")
    [b for b in at.button if b.label == "保存"][0].click().run()
    at.run()

    fav_button = [b for b in at.button if b.key and b.key.startswith("fav_")][0]
    assert fav_button.label == "☆"

    fav_button.click().run()
    fav_button = [b for b in at.button if b.key and b.key.startswith("fav_")][0]
    assert fav_button.label == "⭐"
