import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import psycopg
import pytest

import support_agent
from rag import RagIndex


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
        "配送について",
        "## 配送日数\n\nご注文から通常3営業日以内に発送し、到着までは地域により1〜5日かかります。",
    )
    return index


def test_search_with_retries_finds_match_on_first_attempt():
    index = _build_sample_index()

    sources, attempts = support_agent._search_with_retries(index, "返品したいのですが何日以内ですか")

    assert attempts == 1
    assert sources[0]["title"] == "返品ポリシー > 返品について"


def test_search_with_retries_exhausts_attempts_for_unrelated_query():
    index = _build_sample_index()

    # 索引のどの文書とも関係の薄い質問。1回目で確信度が足りず、2回目(言い換え後)も
    # 見つからないまま、安全ガードの上限(MAX_SEARCH_ATTEMPTS)で打ち切られることを確認する。
    sources, attempts = support_agent._search_with_retries(
        index, "ギターの弾き方を教えてください", max_attempts=2
    )

    assert attempts == 2
    assert sources == []


def test_evaluate_draft_fails_without_sources():
    result = support_agent.evaluate_draft("何らかの回答", [])

    assert result["score"] == 0
    assert result["passed"] is False


def test_evaluate_draft_fails_when_grounding_is_low_even_with_high_confidence():
    """実測で見つかった問題の再現テスト: 検索確信度だけが高くても、回答の中身が
    根拠とまったく無関係なら合格にしてはいけない。"""
    index = _build_sample_index()
    sources = index.search("返品したいのですが何日以内ですか")

    off_topic_answer = "明日の天気は晴れときどき曇りでしょう。傘は不要です。"
    result = support_agent.evaluate_draft(off_topic_answer, sources)

    assert result["passed"] is False
    assert "重なりが低すぎる" in result["reason"] or result["score"] < support_agent.PASS_THRESHOLD


def test_evaluate_draft_passes_when_grounded():
    index = _build_sample_index()
    sources = index.search("返品したいのですが何日以内ですか")

    grounded_answer = "商品到着後7日以内であれば未開封に限り返品を受け付けます。"
    result = support_agent.evaluate_draft(grounded_answer, sources)

    assert result["passed"] is True
    assert result["score"] >= support_agent.PASS_THRESHOLD


def test_save_draft_writes_row_and_returns_id():
    database_url = os.environ["DATABASE_URL"]
    evaluation = {"score": 80, "passed": True, "reason": "テスト用"}
    sources = [{"title": "返品ポリシー > 返品について", "text": "本文", "score": 0.5}]

    draft_id = support_agent.save_draft("返品できますか", "7日以内なら返品できます。", sources, evaluation, 1)

    with psycopg.connect(database_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT question, answer, score, passed, search_attempts FROM support_drafts WHERE id = %s",
            (draft_id,),
        ).fetchone()
    assert row == ("返品できますか", "7日以内なら返品できます。", 80, True, 1)


def test_list_recent_drafts_returns_newest_first():
    evaluation = {"score": 80, "passed": True, "reason": "テスト用"}
    sources = [{"title": "返品ポリシー > 返品について", "text": "本文", "score": 0.5}]

    support_agent.save_draft("古い質問", "回答1", sources, evaluation, 1)
    newest_id = support_agent.save_draft("新しい質問", "回答2", sources, evaluation, 1)

    drafts = support_agent.list_recent_drafts(limit=10)

    assert drafts[0]["id"] == newest_id
    assert drafts[0]["question"] == "新しい質問"


def test_run_agent_saves_grounded_answer_and_passes(monkeypatch):
    index = _build_sample_index()

    def fake_urlopen(request, timeout=15):
        return _fake_response(
            {"content": [{"type": "text", "text": "商品到着後7日以内であれば返品を受け付けます。"}]}
        )

    monkeypatch.setattr(support_agent.urllib.request, "urlopen", fake_urlopen)

    result = support_agent.run_agent("sk-ant-dummy", index, "返品したいのですが何日以内ですか")

    assert result["evaluation"]["passed"] is True
    assert result["search_attempts"] == 1

    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT passed FROM support_drafts WHERE id = %s", (result["draft_id"],)
        ).fetchone()
    assert row == (True,)


def test_run_agent_still_saves_draft_when_api_fails(monkeypatch):
    """安全ガード: 生成に失敗しても、記録そのものは残す(こっそり消さない)。
    passed=Falseとして残るので、画面側で「失敗した」ことが分かる。"""
    index = _build_sample_index()

    def raise_error(request, timeout=15):
        raise OSError("network down")

    monkeypatch.setattr(support_agent.urllib.request, "urlopen", raise_error)

    result = support_agent.run_agent("sk-ant-dummy", index, "返品したいのですが何日以内ですか")

    assert result["evaluation"]["passed"] is False
    assert result["answer"] == ""

    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT passed, reason FROM support_drafts WHERE id = %s", (result["draft_id"],)
        ).fetchone()
    assert row[0] is False
    assert "回答生成に失敗" in row[1]


def test_adoption_stats_returns_none_rate_when_no_drafts():
    stats = support_agent.adoption_stats()

    assert stats == {"total": 0, "passed": 0, "adoption_rate": None}


def test_adoption_stats_computes_passed_ratio():
    evaluation_passed = {"score": 80, "passed": True, "reason": "テスト用"}
    evaluation_failed = {"score": 10, "passed": False, "reason": "テスト用"}
    sources = [{"title": "返品ポリシー", "text": "本文", "score": 0.5}]

    support_agent.save_draft("質問1", "回答1", sources, evaluation_passed, 1)
    support_agent.save_draft("質問2", "回答2", sources, evaluation_passed, 1)
    support_agent.save_draft("質問3", "回答3", sources, evaluation_failed, 1)

    stats = support_agent.adoption_stats()

    assert stats == {"total": 3, "passed": 2, "adoption_rate": pytest.approx(2 / 3)}


def test_adoption_stats_excludes_drafts_outside_window():
    evaluation = {"score": 80, "passed": True, "reason": "テスト用"}
    sources = [{"title": "返品ポリシー", "text": "本文", "score": 0.5}]

    draft_id = support_agent.save_draft("古い質問", "回答", sources, evaluation, 1)
    old_time = datetime.now(timezone.utc) - timedelta(days=40)
    database_url = os.environ["DATABASE_URL"]
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE support_drafts SET created_at = %s WHERE id = %s", (old_time, draft_id)
        )

    stats = support_agent.adoption_stats(window_days=30)

    assert stats == {"total": 0, "passed": 0, "adoption_rate": None}
