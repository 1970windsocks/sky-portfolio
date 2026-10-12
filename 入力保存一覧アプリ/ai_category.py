import json
import urllib.request

# 第63課題: AIをチャットの外で、アプリの機能として使う。
# メモを保存するとき、カテゴリーが空欄だと後から見返しづらい。AIに内容を読ませて
# カテゴリーを提案させることで、入力の手間を減らしつつ、既存のカテゴリー一覧も
# 一緒に渡すことで「仕事」「Work」「work」のような表記ゆれも防ぐ。
#
# 構造化出力(tool_choiceで1つのツールの呼び出しを強制する)を選んだ。
# AIに自由な文章で答えさせると、後ろに余計な説明がついたり表記が揺れたりして
# アプリ側でのパースが不安定になる。ツールの入力スキーマで形を固定すれば、
# 戻り値はアプリがそのまま使えるJSONになる。
MODEL = "claude-haiku-4-5-20251001"
API_URL = "https://api.anthropic.com/v1/messages"

_CATEGORIZE_TOOL = {
    "name": "categorize_memo",
    "description": "メモの内容から、保存に使うカテゴリーを1つ決める。",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "メモに付けるカテゴリー名。既存のカテゴリーに当てはまるものがあれば"
                "そのまま使い、無ければ新しく短い日本語の単語で作る。",
            }
        },
        "required": ["category"],
    },
}


class AiCategorySuggestionError(Exception):
    """AIへの問い合わせが何らかの理由で失敗したことを表す。
    呼び出し側は「提案できなかった」として扱い、保存処理自体は止めない想定。"""


def suggest_category(api_key, text, existing_categories):
    """メモの内容(text)と、このユーザーが既に使っているカテゴリー一覧から、
    カテゴリーを1つ提案する。戻り値は提案されたカテゴリー名の文字列。

    api_keyが無い/空文字のときや、API呼び出しに失敗したときは
    AiCategorySuggestionErrorを送出する(呼び出し側で提案なしとして扱う)。
    """
    if not api_key:
        raise AiCategorySuggestionError("ANTHROPIC_API_KEYが設定されていません")

    system_prompt = (
        "あなたはメモ整理アシスタントです。ユーザーの既存のカテゴリーと一貫性が"
        "保たれるよう、できる限り既存のカテゴリーの中から選んでください。"
        f"既存のカテゴリー一覧: {', '.join(existing_categories) if existing_categories else '(まだ無し)'}"
    )
    payload = json.dumps(
        {
            "model": MODEL,
            "max_tokens": 200,
            "system": system_prompt,
            "messages": [{"role": "user", "content": text}],
            "tools": [_CATEGORIZE_TOOL],
            "tool_choice": {"type": "tool", "name": "categorize_memo"},
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read())
    except Exception as e:
        raise AiCategorySuggestionError(str(e)) from e

    for block in body.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "categorize_memo":
            category = block.get("input", {}).get("category", "").strip()
            if category:
                return category

    raise AiCategorySuggestionError("AIの応答からカテゴリーを取り出せませんでした")
