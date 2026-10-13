import json
from unittest.mock import MagicMock

import pytest

import rag
from rag import RagAnswerError, RagIndex


def _fake_response(payload):
    body = json.dumps(payload).encode("utf-8")
    response = MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def _build_sample_index():
    index = RagIndex()
    index.add_document(
        "返品ポリシー",
        "## 返品について\n\n商品到着後7日以内であれば未開封に限り返品を受け付けます。",
    )
    index.add_document(
        "パスワード再設定",
        "## 再設定の手順\n\nログイン画面の「パスワードを忘れた方はこちら」からメールを受け取り、"
        "リンクを開いて新しいパスワードを設定してください。",
    )
    index.add_document(
        "配送について",
        "## 配送日数\n\nご注文から通常3営業日以内に発送し、到着までは地域により1〜5日かかります。",
    )
    return index


def test_search_finds_the_clearly_relevant_chunk():
    index = _build_sample_index()

    results = index.search("返品したいのですが何日以内ですか")

    assert results
    assert results[0]["title"] == "返品ポリシー > 返品について"


def test_search_returns_empty_for_completely_unrelated_query():
    index = _build_sample_index()

    # 文字bigramによる検索は、索引内のどの文書とも2文字の重なりが一切無い質問に対しては
    # 類似度が常に0になる(共通する重なりが無ければcosine類似度の分子が0のため)。
    results = index.search("好きな食べ物は何ですか")

    assert results == []


def test_answer_question_skips_api_call_when_no_sources_found(monkeypatch):
    index = _build_sample_index()

    def fail_if_called(request, timeout=15):
        raise AssertionError("根拠が無いのにAPIを呼んではいけない")

    monkeypatch.setattr(rag.urllib.request, "urlopen", fail_if_called)

    result = rag.answer_question("sk-ant-dummy", index, "好きな食べ物は何ですか")

    assert result["sources"] == []
    assert "見つかりませんでした" in result["answer"]


def test_answer_question_sends_retrieved_context_and_returns_answer(monkeypatch):
    index = _build_sample_index()
    captured = {}

    def fake_urlopen(request, timeout=15):
        captured["request"] = request
        return _fake_response({"content": [{"type": "text", "text": "7日以内なら返品できます。"}]})

    monkeypatch.setattr(rag.urllib.request, "urlopen", fake_urlopen)

    result = rag.answer_question("sk-ant-dummy", index, "返品したいのですが何日以内ですか")

    sent = json.loads(captured["request"].data)
    assert "返品について" in sent["messages"][0]["content"]
    assert result["answer"] == "7日以内なら返品できます。"
    assert result["sources"][0]["title"] == "返品ポリシー > 返品について"


def test_answer_question_raises_without_api_key_even_with_sources():
    index = _build_sample_index()

    with pytest.raises(RagAnswerError):
        rag.answer_question("", index, "返品したいのですが何日以内ですか")


def test_answer_question_raises_on_api_error(monkeypatch):
    index = _build_sample_index()

    def raise_error(request, timeout=15):
        raise OSError("network down")

    monkeypatch.setattr(rag.urllib.request, "urlopen", raise_error)

    with pytest.raises(RagAnswerError):
        rag.answer_question("sk-ant-dummy", index, "返品したいのですが何日以内ですか")
