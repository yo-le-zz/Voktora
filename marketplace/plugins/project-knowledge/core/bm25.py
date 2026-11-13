"""Index plein texte BM25 maison (incrémental, persistant en JSON) + similarité TF-IDF (cosinus)."""

from __future__ import annotations

import math
from collections import Counter, defaultdict

from .text import tokens


class BM25:
    def __init__(self, k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: dict[str, dict] = {}                  # id → {"len", "meta", "tf"}
        self.post: dict[str, dict[str, int]] = defaultdict(dict)
        self.total_len = 0

    def add(self, doc_id: str, text: str, meta: dict | None = None) -> None:
        self.remove(doc_id)
        tf = Counter(tokens(text))
        n = sum(tf.values())
        self.docs[doc_id] = {"len": n, "meta": meta or {}, "tf": dict(tf)}
        self.total_len += n
        for term, c in tf.items():
            self.post[term][doc_id] = c

    def remove(self, doc_id: str) -> None:
        d = self.docs.pop(doc_id, None)
        if not d:
            return
        self.total_len -= d["len"]
        for term in d["tf"]:
            p = self.post.get(term)
            if p is not None:
                p.pop(doc_id, None)
                if not p:
                    del self.post[term]

    def __len__(self) -> int:
        return len(self.docs)

    def idf(self, term: str) -> float:
        n, df = len(self.docs), len(self.post.get(term, ()))
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, limit: int = 20, prefix: bool = True) -> list[tuple[str, float]]:
        q = tokens(query)
        if not q or not self.docs:
            return []
        avg = self.total_len / len(self.docs) or 1
        scores: dict[str, float] = defaultdict(float)
        for term in dict.fromkeys(q):
            variants = [(term, 1.0)]
            if prefix and len(term) >= 3:
                variants += [(t, 0.5) for t in self.post if t != term and t.startswith(term)][:30]
            for t, w in variants:
                idf = self.idf(t)
                for doc_id, tf in self.post.get(t, {}).items():
                    dl = self.docs[doc_id]["len"]
                    scores[doc_id] += w * idf * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * dl / avg))
        return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]

    # -- similarité TF-IDF (pas d'embeddings : voir README) -------------------------------------------
    def similar(self, query: str, limit: int = 20) -> list[tuple[str, float]]:
        q = Counter(tokens(query))
        if not q or not self.docs:
            return []
        n = len(self.docs)
        qv = {t: (1 + math.log(c)) * math.log(1 + n / (1 + len(self.post.get(t, ())))) for t, c in q.items() if t in self.post}
        qn = math.sqrt(sum(v * v for v in qv.values()))
        if not qn:
            return []
        scores: dict[str, float] = defaultdict(float)
        for t, w in qv.items():
            idf = math.log(1 + n / (1 + len(self.post[t])))
            for doc_id, tf in self.post[t].items():
                scores[doc_id] += w * (1 + math.log(tf)) * idf
        out = []
        for doc_id, dot in scores.items():
            norm = math.sqrt(sum(((1 + math.log(c)) * math.log(1 + n / (1 + len(self.post.get(t, ()))))) ** 2 for t, c in self.docs[doc_id]["tf"].items()))
            out.append((doc_id, dot / (qn * norm) if norm else 0.0))
        return sorted(out, key=lambda kv: (-kv[1], kv[0]))[:limit]

    def to_dict(self) -> dict:
        return {"docs": {k: {"len": v["len"], "meta": v["meta"], "tf": v["tf"]} for k, v in self.docs.items()}}

    @staticmethod
    def from_dict(d: dict) -> BM25:
        ix = BM25()
        for doc_id, v in d.get("docs", {}).items():
            ix.docs[doc_id] = v
            ix.total_len += v["len"]
            for t, c in v["tf"].items():
                ix.post[t][doc_id] = c
        return ix
