import streamlit as st
import json
import os

DATA_FILE = "data.json"

if "editing_id" not in st.session_state:
    st.session_state.editing_id = None

if "username" not in st.session_state:
    st.session_state.username = None


def check_login():
    users = st.secrets.get("users")

    if not users:
        st.error("ユーザーが設定されていません。.streamlit/secrets.toml を確認してください。")
        st.stop()

    if st.session_state.username:
        return

    st.title("ログイン")
    username = st.text_input("ユーザー名を入力してください")
    password = st.text_input("パスワードを入力してください", type="password")
    if st.button("ログイン"):
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
col_title.title(f"入力保存アプリ({st.session_state.username})")
if col_logout.button("ログアウト"):
    st.session_state.username = None
    st.rerun()

data = load_data()
my_data = [item for item in data if item["owner"] == st.session_state.username]

# ① フォーム
text = st.text_input("内容を入力してください")

if st.button("保存"):
    if text.strip() == "":
        st.warning("何か入力してください")
    else:
        # ② 保存(新しいidを振って追加)
        new_id = max([item["id"] for item in data], default=0) + 1
        data.append({"id": new_id, "text": text, "owner": st.session_state.username})
        save_data(data)
        st.success(f"保存しました: {text}")
        st.rerun()

st.divider()

# ③ 一覧
st.subheader("保存した一覧")

if not my_data:
    st.write("まだ何も保存されていません")

for item in my_data:
    col1, col2, col3 = st.columns([6, 1, 1])

    if st.session_state.editing_id == item["id"]:
        # ④ 編集中: 入力欄を表示し、保存し直せるようにする
        new_text = col1.text_input(
            "編集", value=item["text"], key=f"edit_{item['id']}", label_visibility="collapsed"
        )
        if col2.button("保存", key=f"save_{item['id']}"):
            if new_text.strip() == "":
                st.warning("何か入力してください")
            else:
                item["text"] = new_text
                save_data(data)
                st.session_state.editing_id = None
                st.rerun()
    else:
        col1.write(item["text"])
        if col2.button("編集", key=f"edit_btn_{item['id']}"):
            st.session_state.editing_id = item["id"]
            st.rerun()
        if col3.button("削除", key=f"del_{item['id']}"):
            # ④ 削除: この行だけ取り除いて保存し直す
            data = [d for d in data if d["id"] != item["id"]]
            save_data(data)
            st.rerun()
