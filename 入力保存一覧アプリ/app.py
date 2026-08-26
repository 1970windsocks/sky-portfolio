import streamlit as st
import json
import os

import db
import migrate

st.set_page_config(page_title="入力保存アプリ", page_icon="📝", layout="centered")

migrate.run_pending_migrations(os.environ["DATABASE_URL"])

if "editing_id" not in st.session_state:
    st.session_state.editing_id = None

if "username" not in st.session_state:
    st.session_state.username = None


def get_users():
    if st.secrets.load_if_toml_exists():
        users = st.secrets.get("users")
        if users:
            return users

    env_users = os.environ.get("APP_USERS")
    if env_users:
        try:
            return json.loads(env_users)
        except json.JSONDecodeError:
            return None

    return None


def check_login():
    users = get_users()

    if not users:
        st.error("ユーザーが設定されていません。.streamlit/secrets.toml を確認してください。")
        st.stop()

    if st.session_state.username:
        return

    st.title("📝 入力保存アプリ")
    st.subheader("ログイン")

    with st.form("login_form"):
        username = st.text_input("ユーザー名")
        password = st.text_input("パスワード", type="password")
        submitted = st.form_submit_button("ログイン", use_container_width=True)

    if submitted:
        if users.get(username) == password:
            st.session_state.username = username
            st.rerun()
        else:
            st.error("ユーザー名またはパスワードが違います")

    st.stop()


check_login()


col_title, col_logout = st.columns([5, 1])
col_title.title("📝 入力保存アプリ")
if col_logout.button("ログアウト", use_container_width=True):
    st.session_state.username = None
    st.session_state.editing_id = None
    st.rerun()
st.caption(f"ログイン中: {st.session_state.username} さん")

my_data = db.list_memos(st.session_state.username)

# ① フォーム
with st.form("add_form", clear_on_submit=True):
    text = st.text_input("内容を入力してください")
    submitted = st.form_submit_button("保存", use_container_width=True)

if submitted:
    if text.strip() == "":
        st.warning("何か入力してください")
    else:
        # ② 保存
        db.insert_memo(st.session_state.username, text)
        st.success(f"保存しました: {text}")

st.divider()

# ③ 一覧
st.subheader("保存した一覧")
st.caption(f"現在 {len(my_data)} 件保存されています")

if not my_data:
    st.write("まだ何も保存されていません")

for item in my_data:
    with st.container(border=True):
        if st.session_state.editing_id == item["id"]:
            # ④ 編集中: 入力欄を表示し、保存し直せるようにする
            new_text = st.text_input(
                "編集", value=item["text"], key=f"edit_{item['id']}", label_visibility="collapsed"
            )
            col1, col2 = st.columns(2)
            if col1.button("💾 保存", key=f"save_{item['id']}", use_container_width=True):
                if new_text.strip() == "":
                    st.warning("何か入力してください")
                else:
                    db.update_memo(item["id"], new_text)
                    st.session_state.editing_id = None
                    st.rerun()
            if col2.button("✖️ キャンセル", key=f"cancel_{item['id']}", use_container_width=True):
                st.session_state.editing_id = None
                st.rerun()
        else:
            col1, col2, col3, col4 = st.columns([5, 1, 1, 1])
            col1.write(item["text"])
            if col2.button("⭐" if item["is_favorite"] else "☆", key=f"fav_{item['id']}", help="お気に入り"):
                db.set_favorite(item["id"], not item["is_favorite"])
                st.rerun()
            if col3.button("✏️", key=f"edit_btn_{item['id']}", help="編集"):
                st.session_state.editing_id = item["id"]
                st.rerun()
            if col4.button("🗑️", key=f"del_{item['id']}", help="削除"):
                # ④ 削除
                db.delete_memo(item["id"])
                st.rerun()
