import json
import math
import re
import urllib.request
from collections import Counter

# 第64課題: 自分の持つ文書に基づいてAIに答えさせる仕組み(RAG = 検索Retrieve + 生成Generate)。
#
# 検索(①②の「取り込む」「意味で探す」部分)は、外部の埋め込みAPIを使わずローカルで
# 計算できるTF-IDF + 文字bigramによる類似度検索で実装した。日本語は単語の間に
# スペースが無く、素朴な単語分割(空白区切り)が効かないため、2文字ずつの重なり窓
# (bigram)を「単語」の代わりに使う。これは外部APIが無くても実際に動く、本物の
# 意味寄り検索(表記が多少違っても、共通する文字の並びが多ければ一致度が上がる)。
#
# 生成(②の「答えさせる」部分の文章化)はClaude APIを使う。ai_category.pyと同じ、
# このプロジェクトの慣習(urllib.request直書き、共通HTTPクライアントは作らない)に合わせている。
MODEL = "claude-haiku-4-5-20251001"
API_URL = "https://api.anthropic.com/v1/messages"


def _ngrams(text, n=2):
    normalized = re.sub(r"\s+", "", text)
    if len(normalized) < n:
        return [normalized] if normalized else []
    return [normalized[i : i + n] for i in range(len(normalized) - n + 1)]


def _split_into_chunks(title, text):
    """"## 見出し" ごとに1チャンクへ分割する(条文単位で根拠を示せるようにするため)。
    見出しが無い文書(TOKUSHOHO_TEXTのような表形式)は全体を1チャンクとして扱う。"""
    lines = text.splitlines()
    chunks = []
    current_heading = title
    current_lines = []

    def flush():
        body = "\n".join(current_lines).strip()
        if body:
            chunks.append((current_heading, body))

    for line in lines:
        if line.startswith("## "):
            flush()
            current_heading = f"{title} > {line[3:].strip()}"
            current_lines = []
        elif line.startswith("# "):
            continue  # 文書全体のタイトル行はチャンクに含めない
        else:
            current_lines.append(line)
    flush()

    return chunks if chunks else [(title, text.strip())]


class RagIndex:
    """文書をチャンクに分けてTF-IDFベクトルで検索できるようにする、最小限の索引。"""

    def __init__(self):
        self._chunks = []  # [{"title": 見出し, "text": 本文, "tf": Counter}]
        self._df = Counter()  # 各bigramが何チャンクに出現するか

    def add_document(self, title, text):
        for heading, body in _split_into_chunks(title, text):
            tf = Counter(_ngrams(body))
            self._chunks.append({"title": heading, "text": body, "tf": tf})
            for term in tf:
                self._df[term] += 1

    def _tfidf_vector(self, tf):
        n_docs = len(self._chunks)
        vec = {}
        for term, count in tf.items():
            df = self._df.get(term, 0)
            if df == 0:
                continue
            idf = math.log((n_docs + 1) / (df + 1)) + 1
            vec[term] = count * idf
        return vec

    @staticmethod
    def _cosine(vec_a, vec_b):
        common = set(vec_a) & set(vec_b)
        if not common:
            return 0.0
        dot = sum(vec_a[t] * vec_b[t] for t in common)
        norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
        norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def search(self, query, top_k=3):
        query_vec = self._tfidf_vector(Counter(_ngrams(query)))
        scored = []
        for chunk in self._chunks:
            score = self._cosine(query_vec, self._tfidf_vector(chunk["tf"]))
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {"title": chunk["title"], "text": chunk["text"], "score": score}
            for score, chunk in scored[:top_k]
        ]


class RagAnswerError(Exception):
    """生成(Claude APIでの文章化)が失敗したことを表す。"""


def answer_question(api_key, index, question, top_k=3):
    """検索(index.search)で見つけた根拠だけを材料にAIへ回答させる。
    戻り値: {"answer": 回答文, "sources": [{"title", "text", "score"}, ...]}

    根拠が1件も見つからなければAPIを呼ばずに「わかりません」を返す
    (関係ない資料を無理やり使って、それらしい誤答をでっち上げる=ハルシネーションを防ぐ)。
    """
    sources = index.search(question, top_k=top_k)
    if not sources:
        return {
            "answer": "手元の資料からは、この質問に関係しそうな記載が見つかりませんでした。",
            "sources": [],
        }

    if not api_key:
        raise RagAnswerError("ANTHROPIC_API_KEYが設定されていません")

    context = "\n\n".join(f"【{s['title']}】\n{s['text']}" for s in sources)
    prompt = (
        "以下は社内文書からの抜粋です。この内容だけを根拠にして質問に答えてください。"
        "抜粋に書かれていないことは、推測せずに「資料からは分かりません」と答えてください。\n\n"
        f"{context}\n\n質問: {question}"
    )

    payload = json.dumps(
        {
            "model": MODEL,
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
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
        raise RagAnswerError(str(e)) from e

    for block in body.get("content", []):
        if block.get("type") == "text" and block.get("text", "").strip():
            return {"answer": block["text"].strip(), "sources": sources}

    raise RagAnswerError("AIの応答からテキストを取り出せませんでした")
