import streamlit as st
import os

import auth
import db
import migrate

st.set_page_config(page_title="入力保存アプリ", page_icon="📝", layout="centered")

migrate.run_pending_migrations(os.environ["DATABASE_URL"])

if "editing_id" not in st.session_state:
    st.session_state.editing_id = None

if "username" not in st.session_state:
    st.session_state.username = None

if "role" not in st.session_state:
    st.session_state.role = None


def show_flash():
    if "flash_message" in st.session_state:
        if st.session_state.get("flash_is_error"):
            st.error(st.session_state.flash_message)
        else:
            st.success(st.session_state.flash_message)
        del st.session_state["flash_message"]
        st.session_state.pop("flash_is_error", None)


def show_verify_screen(token):
    success, message = auth.verify_email(token)
    st.session_state.flash_message = message
    st.session_state.flash_is_error = not success
    st.query_params.clear()
    st.rerun()


def show_reset_screen(token):
    st.title("📝 入力保存アプリ")
    st.subheader("新しいパスワードを設定")

    with st.form("reset_form"):
        new_password = st.text_input("新しいパスワード", type="password", key="reset_password")
        confirm = st.text_input("新しいパスワード(確認)", type="password", key="reset_password_confirm")
        submitted = st.form_submit_button("パスワードを再設定する", use_container_width=True)

    if submitted:
        if new_password.strip() == "":
            st.warning("パスワードを入力してください")
        elif len(new_password) < 8:
            st.warning("パスワードは8文字以上にしてください")
        elif new_password != confirm:
            st.warning("パスワードが一致しません")
        else:
            success, message = auth.reset_password(token, new_password)
            if success:
                st.session_state.flash_message = message
                st.query_params.clear()
                st.rerun()
            else:
                st.error(message)

    st.stop()


def check_login():
    if st.session_state.username:
        return

    show_flash()

    st.title("📝 入力保存アプリ")

    tab_login, tab_signup = st.tabs(["ログイン", "新規登録"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("ユーザー名", key="login_username")
            password = st.text_input("パスワード", type="password", key="login_password")
            submitted = st.form_submit_button("ログイン", use_container_width=True)

        if submitted:
            user, error = auth.authenticate(username, password)
            if user:
                st.session_state.username = user["username"]
                st.session_state.role = user["role"]
                st.rerun()
            else:
                st.error(error)

        with st.expander("パスワードを忘れた方はこちら"):
            with st.form("forgot_form"):
                email = st.text_input("登録したメールアドレス", key="forgot_email")
                forgot_submitted = st.form_submit_button("再設定メールを送る", use_container_width=True)
            if forgot_submitted:
                if email.strip() == "":
                    st.warning("メールアドレスを入力してください")
                else:
                    message = auth.request_password_reset(email.strip())
                    st.success(message)

    with tab_signup:
        with st.form("signup_form"):
            new_username = st.text_input("ユーザー名", key="signup_username")
            new_email = st.text_input("メールアドレス", key="signup_email")
            new_password = st.text_input("パスワード(8文字以上)", type="password", key="signup_password")
            signup_submitted = st.form_submit_button("登録する", use_container_width=True)

        if signup_submitted:
            if not new_username.strip() or not new_email.strip() or not new_password.strip():
                st.warning("すべて入力してください")
            elif len(new_password) < 8:
                st.warning("パスワードは8文字以上にしてください")
            else:
                success, message = auth.create_user(
                    new_username.strip(), new_email.strip(), new_password
                )
                if success:
                    st.success(message)
                else:
                    st.error(message)

    st.stop()


# メール確認・パスワード再設定のリンクは、ログイン前でも処理する
if "verify" in st.query_params:
    show_verify_screen(st.query_params["verify"])
elif "reset" in st.query_params:
    show_reset_screen(st.query_params["reset"])

check_login()


col_title, col_logout = st.columns([5, 1])
col_title.title("📝 入力保存アプリ")
if col_logout.button("ログアウト", use_container_width=True):
    st.session_state.username = None
    st.session_state.role = None
    st.session_state.editing_id = None
    st.rerun()
st.caption(f"ログイン中: {st.session_state.username} さん")

if st.session_state.role == "admin":
    with st.expander("🛠️ 管理者ダッシュボード"):
        stats = auth.admin_stats()
        col1, col2 = st.columns(2)
        col1.metric("登録ユーザー数", stats["user_count"])
        col2.metric("全体の保存件数", stats["memo_count"])

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
