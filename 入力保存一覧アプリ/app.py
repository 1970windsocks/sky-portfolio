import streamlit as st
import json
import os

DATA_FILE = "data.json"

st.set_page_config(page_title="入力保存アプリ", page_icon="📝", layout="centered")

if "editing_id" not in st.session_state:
    st.session_state.editing_id = None

if "username" not in st.session_state:
    st.session_state.username = None


def get_users():
    try:
        users = st.secrets.get("users")
        if users:
            return users
    except FileNotFoundError:
        pass

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


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                st.warning("保存データが読み込めなかったため、空の状態から始めます。")
                data = []
    else:
        data = []

    # 古いデータ(idが無いもの)にidを振る
    next_id = 1
    for item in data:
        if "id" not in item:
            item["id"] = next_id
        next_id = max(next_id, item["id"] + 1)

    # 古いデータ(ownerが無いもの)は自分のデータとして扱う
    for item in data:
        if "owner" not in item:
            item["owner"] = st.session_state.username

    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


col_title, col_logout = st.columns([5, 1])
col_title.title("📝 入力保存アプリ")
if col_logout.button("ログアウト", use_container_width=True):
    st.session_state.username = None
    st.session_state.editing_id = None
    st.rerun()
st.caption(f"ログイン中: {st.session_state.username} さん")

data = load_data()
my_data = [item for item in data if item["owner"] == st.session_state.username]

# ① フォーム
with st.form("add_form", clear_on_submit=True):
    text = st.text_input("内容を入力してください")
    submitted = st.form_submit_button("保存", use_container_width=True)

if submitted:
    if text.strip() == "":
        st.warning("何か入力してください")
    else:
        # ② 保存(新しいidを振って追加)
        new_id = max([item["id"] for item in data], default=0) + 1
        data.append({"id": new_id, "text": text, "owner": st.session_state.username})
        save_data(data)
        st.success(f"保存しました: {text}")

st.divider()

# ③ 一覧
st.subheader("保存した一覧")

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
                    item["text"] = new_text
                    save_data(data)
                    st.session_state.editing_id = None
                    st.rerun()
            if col2.button("✖️ キャンセル", key=f"cancel_{item['id']}", use_container_width=True):
                st.session_state.editing_id = None
                st.rerun()
        else:
            col1, col2, col3 = st.columns([6, 1, 1])
            col1.write(item["text"])
            if col2.button("✏️", key=f"edit_btn_{item['id']}", help="編集"):
                st.session_state.editing_id = item["id"]
                st.rerun()
            if col3.button("🗑️", key=f"del_{item['id']}", help="削除"):
                # ④ 削除: この行だけ取り除いて保存し直す
                data = [d for d in data if d["id"] != item["id"]]
                save_data(data)
                st.rerun()
