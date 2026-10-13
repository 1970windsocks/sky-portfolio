import json
import os
import urllib.request

import psycopg

import rag

# 第65課題: AIに複数ステップを自分で判断して進めさせる(エージェント)。
# 「①調べる→②まとめる・測る→③保存する」の3ステップを、人の手を介さず自律的に進める。
# ただし自律だからこそ、安全ガード(やっていいことの範囲・回数上限・危険操作の禁止)を
# コード側で強制する。プロンプトで「〜してください」とお願いするだけでは、
# AIが指示を外れたときに歯止めが無い。

MODEL = rag.MODEL
API_URL = rag.API_URL

MAX_SEARCH_ATTEMPTS = 2  # 安全ガード: 検索の言い換えをこの回数で必ず打ち切る(無限ループ防止)
MIN_CONFIDENCE = 0.1  # 実測(関係ない質問でも文書のボイラープレートと0.07程度は重なる)を踏まえた最低ライン
PASS_THRESHOLD = 40  # 100点満点中、これ未満は「要レビュー」扱い
MIN_GROUNDING_RATIO = 0.2  # 合格に必須の下限(下の注意書き参照)


class AgentError(Exception):
    """生成(Claude API呼び出し)が失敗したことを表す。"""


def _connect():
    return psycopg.connect(os.environ["DATABASE_URL"])


def _reformulate_query(question):
    """検索の自信(確信度)が低いとき、質問文の末尾の丁寧表現を削ってキーワードに寄せ、
    もう一度検索するための簡易な言い換え(本物の言い換えAPIは使わない、ルールベース)。"""
    trimmed = question
    for suffix in ("でしょうか", "ますか", "ですか", "か?", "か?", "?", "?"):
        if trimmed.endswith(suffix):
            trimmed = trimmed[: -len(suffix)]
            break
    return trimmed.strip() or question


def _search_with_retries(index, question, max_attempts=MAX_SEARCH_ATTEMPTS):
    """①調べる。確信度(上位スコア)がMIN_CONFIDENCE未満なら、質問を言い換えて
    もう一度検索する。ただしmax_attempts回で必ず止まる(安全ガード: 回数の上限)。

    戻り値: (sources, 実際に使った検索回数)
    """
    query = question
    sources = []
    for attempt in range(1, max_attempts + 1):
        results = index.search(query)
        if results and results[0]["score"] >= MIN_CONFIDENCE:
            return results, attempt
        sources = results
        query = _reformulate_query(question)
    return sources, max_attempts


def _generate_answer(api_key, question, sources):
    """②まとめる。①で見つかった根拠だけを材料にAIへ回答させる(ai_category.py・rag.pyと
    同じ、urllib.request直書きの方式)。根拠が無ければAPIを呼ばずに「わかりません」を返す。"""
    if not sources:
        return "手元の資料からは、この質問に関係しそうな記載が見つかりませんでした。"

    if not api_key:
        raise AgentError("ANTHROPIC_API_KEYが設定されていません")

    context = "\n\n".join(f"【{s['title']}】\n{s['text']}" for s in sources)
    prompt = (
        "以下は社内文書からの抜粋です。この内容だけを根拠にして質問に答えてください。"
        "抜粋に書かれていないことは、推測せずに「資料からは分かりません」と答えてください。\n\n"
        f"{context}\n\n質問: {question}"
    )
    payload = json.dumps(
        {"model": MODEL, "max_tokens": 500, "messages": [{"role": "user", "content": prompt}]}
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
        raise AgentError(str(e)) from e

    for block in body.get("content", []):
        if block.get("type") == "text" and block.get("text", "").strip():
            return block["text"].strip()
    raise AgentError("AIの応答からテキストを取り出せませんでした")


def _grounding_ratio(answer, sources):
    """回答の中に、根拠チャンクの文字bigramがどれだけ含まれているかの粗い近似。
    「本当に渡した資料を見て答えているか」を外部APIなしで測る目安。"""
    answer_terms = set(rag._ngrams(answer))
    if not answer_terms:
        return 0.0
    source_terms = set()
    for s in sources:
        source_terms |= set(rag._ngrams(s["text"]))
    if not source_terms:
        return 0.0
    overlap = answer_terms & source_terms
    return len(overlap) / len(answer_terms)


def evaluate_draft(answer, sources):
    """②測る。AIに採点させる代わりに、基準で点数化する(0〜100点)。

    検索確信度(上位スコア、50点満点)と、回答が根拠の言葉をどれだけ使っているか
    (グラウンディング度、50点満点)を合算する。

    注意(正直な限界、実測で見つかった問題): このグラウンディング度は「渡した根拠を
    無視せず使っているか」は測れるが、「そもそも渡した根拠が質問に合っているか」は
    測れない。第64課題で見つかった「短い無関係な条文が検索で上位に来る」問題そのものは、
    この評価だけでは防げない — 画面側で根拠を必ず表示し、人間が確認する設計に
    引き続き頼っている。

    さらに、単純にconfidence_scoreとgrounding_scoreを合算するだけだと、検索確信度が
    そこそこ高ければ、回答の中身が根拠とまったく無関係でも合算スコアだけで合格ラインを
    超えてしまうことが実測で判明した(例: 検索確信度45点+グラウンディング2点=47点で
    合格扱いになってしまった)。そのため、グラウンディング度がMIN_GROUNDING_RATIO未満の
    場合は、合算スコアに関わらず不合格にする(回答の中身が根拠を全く使っていないなら、
    どれだけ良い資料が見つかっていても信用できないため)。
    """
    if not sources:
        return {"score": 0, "passed": False, "reason": "根拠となる資料が見つからなかった"}
    if not answer or len(answer.strip()) < 10:
        return {"score": 10, "passed": False, "reason": "回答が短すぎる、または空"}

    top_score = sources[0]["score"]
    confidence_score = min(top_score * 250, 50)
    grounded_ratio = _grounding_ratio(answer, sources)
    grounding_score = grounded_ratio * 50

    total = round(confidence_score + grounding_score)
    passed = total >= PASS_THRESHOLD and grounded_ratio >= MIN_GROUNDING_RATIO
    reason = (
        f"検索確信度={top_score:.2f}({confidence_score:.0f}/50点), "
        f"根拠との重なり={grounded_ratio:.2f}({grounding_score:.0f}/50点)"
    )
    if total >= PASS_THRESHOLD and grounded_ratio < MIN_GROUNDING_RATIO:
        reason += "(合算点は基準以上だが、根拠との重なりが低すぎるため不合格)"
    return {"score": total, "passed": passed, "reason": reason}


def save_draft(question, answer, sources, evaluation, search_attempts):
    """③保存する。安全ガード: エージェントが書き込めるのはこのsupport_draftsテーブルだけ。
    顧客に実際に送る・他のテーブル(memos等)を変更する、といった操作は一切行わない。
    評価がPASS_THRESHOLD未満でも保存はするが、passed=Falseのまま残すことで、
    自信の無い回答を自信満々に見せてしまうことを防ぐ(画面側で「要レビュー」と分かる)。
    """
    source_titles = json.dumps([s["title"] for s in sources], ensure_ascii=False)
    with _connect() as conn:
        row = conn.execute(
            "INSERT INTO support_drafts "
            "(question, answer, sources, score, passed, reason, search_attempts) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                question,
                answer,
                source_titles,
                evaluation["score"],
                evaluation["passed"],
                evaluation["reason"],
                search_attempts,
            ),
        ).fetchone()
    return row[0]


def list_recent_drafts(limit=10):
    """管理画面でのレビュー用。新しい順に返す。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, question, answer, score, passed, reason, search_attempts, created_at "
            "FROM support_drafts ORDER BY id DESC LIMIT %s",
            (limit,),
        ).fetchall()
    columns = [
        "id",
        "question",
        "answer",
        "score",
        "passed",
        "reason",
        "search_attempts",
        "created_at",
    ]
    return [dict(zip(columns, row)) for row in rows]


def run_agent(api_key, index, question, max_search_attempts=MAX_SEARCH_ATTEMPTS):
    """①調べる→②まとめる・測る→③保存する、を自律的に進める小さなエージェント。

    戻り値: {"draft_id", "question", "answer", "sources", "evaluation", "search_attempts"}
    """
    sources, attempts_used = _search_with_retries(index, question, max_search_attempts)

    try:
        answer = _generate_answer(api_key, question, sources)
    except AgentError as e:
        answer = ""
        evaluation = {"score": 0, "passed": False, "reason": f"回答生成に失敗: {e}"}
        draft_id = save_draft(question, answer, sources, evaluation, attempts_used)
        return {
            "draft_id": draft_id,
            "question": question,
            "answer": answer,
            "sources": sources,
            "evaluation": evaluation,
            "search_attempts": attempts_used,
        }

    evaluation = evaluate_draft(answer, sources)
    draft_id = save_draft(question, answer, sources, evaluation, attempts_used)

    return {
        "draft_id": draft_id,
        "question": question,
        "answer": answer,
        "sources": sources,
        "evaluation": evaluation,
        "search_attempts": attempts_used,
    }
