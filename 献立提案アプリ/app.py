import streamlit as st
import requests
import re
import os
import anthropic

st.set_page_config(page_title="今日の献立提案", page_icon="🍳", layout="centered")

FILTER_ENDPOINT = "https://www.themealdb.com/api/json/v1/1/filter.php"
LOOKUP_ENDPOINT = "https://www.themealdb.com/api/json/v1/1/lookup.php"
LIST_ENDPOINT = "https://www.themealdb.com/api/json/v1/1/list.php"
TRANSLATE_ENDPOINT = "https://api.mymemory.translated.net/get"

st.title("🍳 今日の献立提案")
st.caption("冷蔵庫にある食材を入力すると、それを使えるレシピを日本語で提案します")


def get_credential(key):
    if st.secrets.load_if_toml_exists():
        value = st.secrets.get(key)
        if value:
            return value

    return os.environ.get(key)


@st.cache_data(ttl=86400)
def summarize_instructions(instructions, api_key):
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-opus-5",
        max_tokens=1024,
        thinking={"type": "disabled"},
        output_config={"effort": "low"},
        messages=[
            {
                "role": "user",
                "content": (
                    "次は英語のレシピの作り方です。日本語で3〜5個の短い手順に要約してください。"
                    "手順のリストだけを出力してください。\n\n" + instructions
                ),
            }
        ],
    )
    return next((b.text for b in response.content if b.type == "text"), "")


def chunk_text(text, max_len=450):
    chunks = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > max_len:
            if current:
                chunks.append(current)
            current = line[:max_len]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [text[:max_len]]


@st.cache_data(ttl=86400)
def translate(text, source, target):
    if not text or not text.strip():
        return text

    translated_parts = []
    for chunk in chunk_text(text):
        try:
            res = requests.get(
                TRANSLATE_ENDPOINT,
                params={"q": chunk, "langpair": f"{source}|{target}"},
                timeout=10,
            )
            res.raise_for_status()
            translated_parts.append(
                res.json().get("responseData", {}).get("translatedText", chunk)
            )
        except requests.RequestException:
            translated_parts.append(chunk)
    return "\n".join(translated_parts)


@st.cache_data(ttl=86400)
def fetch_ingredient_catalog():
    res = requests.get(LIST_ENDPOINT, params={"i": "list"}, timeout=10)
    res.raise_for_status()
    meals = res.json().get("meals") or []
    return [m["strIngredient"] for m in meals]


def resolve_ingredient(word, catalog):
    word_lower = word.strip().lower()
    if not word_lower:
        return None

    for name in catalog:
        if name.lower() == word_lower:
            return name

    candidates = [name for name in catalog if word_lower in name.lower()]
    if candidates:
        return min(candidates, key=len)

    return None


@st.cache_data(ttl=3600)
def fetch_meals_by_ingredient(ingredient):
    res = requests.get(
        FILTER_ENDPOINT, params={"i": ingredient.replace(" ", "_")}, timeout=10
    )
    res.raise_for_status()
    return res.json().get("meals") or []


@st.cache_data(ttl=3600)
def fetch_meal_detail(meal_id):
    res = requests.get(LOOKUP_ENDPOINT, params={"i": meal_id}, timeout=10)
    res.raise_for_status()
    meals = res.json().get("meals") or []
    return meals[0] if meals else None


def meal_ingredients(detail):
    items = []
    for i in range(1, 21):
        name = detail.get(f"strIngredient{i}")
        amount = detail.get(f"strMeasure{i}")
        if name and name.strip():
            items.append(f"{name.strip()} ({amount.strip()})" if amount and amount.strip() else name.strip())
    return items


ingredients_text = st.text_input(
    "冷蔵庫にある食材(、または , で区切ってください)", placeholder="例: 鶏肉、玉ねぎ、人参"
)

if st.button("献立を提案する", use_container_width=True):
    ingredients_ja = [i.strip() for i in re.split(r"[,、，]", ingredients_text) if i.strip()]

    if not ingredients_ja:
        st.warning("食材を1つ以上入力してください")
    else:
        match_count = {}
        errors = 0

        with st.spinner("レシピを探しています..."):
            try:
                catalog = fetch_ingredient_catalog()
            except requests.RequestException:
                catalog = []

            ingredients_en = [translate(ing, "ja", "en") for ing in ingredients_ja]
            resolved = [resolve_ingredient(ing, catalog) for ing in ingredients_en]
            unmatched = [ja for ja, en in zip(ingredients_ja, resolved) if en is None]
            resolved = [ing for ing in resolved if ing is not None]

            for ing in resolved:
                try:
                    meals = fetch_meals_by_ingredient(ing)
                except requests.RequestException:
                    errors += 1
                    continue
                for m in meals:
                    meal_id = m["idMeal"]
                    match_count[meal_id] = match_count.get(meal_id, 0) + 1

            if unmatched:
                st.caption(f"認識できなかった食材: {', '.join(unmatched)}")

            if not match_count:
                if resolved and errors == len(resolved):
                    st.error("レシピの取得に失敗しました。時間をおいて試してください。")
                else:
                    st.info("該当するレシピが見つかりませんでした。別の食材で試してみてください。")
            else:
                top_ids = sorted(match_count, key=match_count.get, reverse=True)[:5]

                st.subheader("提案レシピ")
                for meal_id in top_ids:
                    try:
                        detail = fetch_meal_detail(meal_id)
                    except requests.RequestException:
                        continue
                    if not detail:
                        continue

                    title_ja = translate(detail.get("strMeal", ""), "en", "ja")
                    ingredients_block_ja = translate(
                        " / ".join(meal_ingredients(detail)), "en", "ja"
                    )

                    with st.container(border=True):
                        col_img, col_info = st.columns([1, 3])
                        if detail.get("strMealThumb"):
                            col_img.image(detail["strMealThumb"])
                        col_info.markdown(f"**{title_ja or detail.get('strMeal', '（タイトル不明）')}**")
                        col_info.caption(f"入力した食材のうち {match_count[meal_id]} 件がこのレシピに関連しています")
                        col_info.write("材料: " + ingredients_block_ja)
                        if detail.get("strSource"):
                            col_info.markdown(f"[レシピの詳細を見る(英語)]({detail['strSource']})")

                        api_key = get_credential("ANTHROPIC_API_KEY")
                        if not detail.get("strInstructions"):
                            pass
                        elif not api_key:
                            col_info.caption("(AI要約を使うには ANTHROPIC_API_KEY の設定が必要です)")
                        elif col_info.button("🤖 作り方をAIで要約する", key=f"summarize_{meal_id}"):
                            with st.spinner("要約しています..."):
                                try:
                                    summary = summarize_instructions(
                                        detail["strInstructions"], api_key
                                    )
                                    col_info.markdown("**作り方の要約:**")
                                    col_info.write(summary)
                                except anthropic.AuthenticationError:
                                    col_info.error("Claude APIキーが正しくありません。")
                                except anthropic.RateLimitError:
                                    col_info.error("APIの利用上限に達しました。しばらくしてから試してください。")
                                except anthropic.APIError:
                                    col_info.error("要約の取得に失敗しました。時間をおいて試してください。")
