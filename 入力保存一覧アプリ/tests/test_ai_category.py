import json
from unittest.mock import MagicMock

import pytest

import ai_category


def _fake_response(payload):
    body = json.dumps(payload).encode("utf-8")
    response = MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def _tool_use_payload(category):
    return {
        "content": [
            {"type": "tool_use", "name": "categorize_memo", "input": {"category": category}}
        ]
    }


def test_suggest_category_returns_tool_input_on_success(monkeypatch):
    monkeypatch.setattr(
        ai_category.urllib.request,
        "urlopen",
        lambda request, timeout=15: _fake_response(_tool_use_payload("仕事")),
    )

    result = ai_category.suggest_category("sk-ant-dummy", "明日までに資料を提出する", ["仕事", "買い物"])

    assert result == "仕事"


def test_suggest_category_sends_tool_choice_and_existing_categories(monkeypatch):
    """構造化出力(tool_choiceでツール呼び出しを強制する)になっていることと、
    既存カテゴリーが一貫性のためにプロンプトへ渡っていることを確認する。"""
    captured = {}

    def fake_urlopen(request, timeout=15):
        captured["request"] = request
        return _fake_response(_tool_use_payload("買い物"))

    monkeypatch.setattr(ai_category.urllib.request, "urlopen", fake_urlopen)

    ai_category.suggest_category("sk-ant-dummy", "牛乳を買う", ["仕事", "買い物"])

    sent = json.loads(captured["request"].data)
    assert sent["tool_choice"] == {"type": "tool", "name": "categorize_memo"}
    assert sent["tools"][0]["name"] == "categorize_memo"
    assert "仕事" in sent["system"]
    assert "買い物" in sent["system"]


def test_suggest_category_raises_when_api_key_missing():
    with pytest.raises(ai_category.AiCategorySuggestionError):
        ai_category.suggest_category("", "メモの内容", [])


def test_suggest_category_raises_on_http_error(monkeypatch):
    def raise_error(request, timeout=15):
        raise OSError("network down")

    monkeypatch.setattr(ai_category.urllib.request, "urlopen", raise_error)

    with pytest.raises(ai_category.AiCategorySuggestionError):
        ai_category.suggest_category("sk-ant-dummy", "メモの内容", [])


def test_suggest_category_raises_when_no_tool_use_block(monkeypatch):
    payload = {"content": [{"type": "text", "text": "すみません、わかりません"}]}
    monkeypatch.setattr(
        ai_category.urllib.request, "urlopen", lambda request, timeout=15: _fake_response(payload)
    )

    with pytest.raises(ai_category.AiCategorySuggestionError):
        ai_category.suggest_category("sk-ant-dummy", "メモの内容", [])
