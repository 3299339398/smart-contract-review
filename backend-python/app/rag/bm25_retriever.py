"""BM25 关键词检索器 —— 中文法律文本检索，支持持久化。"""

import logging
import pickle
from pathlib import Path
from typing import List, Dict, Optional
from rank_bm25 import BM25Okapi
import jieba

logger = logging.getLogger(__name__)

# BM25 索引快照持久化目录
_INDEX_DIR = Path(__file__).parent.parent.parent / "data" / "bm25_index"


class BM25Retriever:
    """BM25 关键词检索，jieba 分词 + pickle 持久化。"""

    def __init__(self):
        self._clauses: List[Dict] = []
        self._tokenized_corpus: List[List[str]] = []
        self._bm25: Optional[BM25Okapi] = None
        self._doc_id: Optional[int] = None
        self._dirty = False
        self._indices: Dict[int, tuple[List[Dict], List[List[str]], BM25Okapi]] = {}

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        tokens = jieba.lcut(text.lower())
        return [t.strip() for t in tokens if t.strip()]

    def index(self, clauses: List[Dict], doc_id: Optional[int] = None):
        """基于条款列表构建 BM25 索引。"""
        self._clauses = clauses
        self._tokenized_corpus = [self._tokenize(c.get("text", "")) for c in clauses]
        if self._tokenized_corpus:
            self._bm25 = BM25Okapi(self._tokenized_corpus)
            if doc_id is not None:
                self._indices[doc_id] = (
                    self._clauses, self._tokenized_corpus, self._bm25
                )
                self._doc_id = doc_id
            self._dirty = True
            logger.info(f"BM25 index built with {len(clauses)} clauses")
        else:
            self._bm25 = None
            if doc_id is not None:
                self._indices.pop(doc_id, None)
                self._doc_id = doc_id

    def search(self, query: str, top_k: int = 5, doc_id: Optional[int] = None) -> List[Dict]:
        """按 BM25 得分检索 top-k 条款，返回 [0, 1] 归一化分数。"""
        index = self._indices.get(doc_id) if doc_id is not None else None
        if doc_id is not None and index is None:
            return []
        if index is not None:
            clauses, _, bm25 = index
        else:
            clauses, bm25 = self._clauses, self._bm25
        if not bm25 or not clauses:
            return []

        tokenized_query = self._tokenize(query)
        scores = bm25.get_scores(tokenized_query)

        scored = [(scores[i], i) for i in range(len(scores)) if scores[i] > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]

        max_score = top[0][0] if top else 1.0
        results = []
        for score, idx in top:
            results.append({
                "clause_index": clauses[idx].get("index", idx),
                "text": clauses[idx].get("text", ""),
                "bm25_score": round(score / max_score, 4) if max_score > 0 else 0
            })
        return results

    def save(self, doc_id: int) -> bool:
        """通过 pickle 将 BM25 索引持久化到磁盘。"""
        if not self._bm25 or not self._dirty:
            return False
        try:
            _INDEX_DIR.mkdir(parents=True, exist_ok=True)
            path = _INDEX_DIR / f"bm25_doc_{doc_id}.pkl"
            with open(path, "wb") as f:
                pickle.dump({
                    "clauses": self._clauses,
                    "tokenized_corpus": self._tokenized_corpus,
                }, f)
            self._dirty = False
            self._indices[doc_id] = (self._clauses, self._tokenized_corpus, self._bm25)
            logger.info(f"BM25 index saved: {path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to save BM25 index: {e}")
            return False

    def load(self, doc_id: int) -> bool:
        """从磁盘加载 BM25 索引。"""
        try:
            path = _INDEX_DIR / f"bm25_doc_{doc_id}.pkl"
            if not path.exists():
                return False
            with open(path, "rb") as f:
                data = pickle.load(f)
            self._clauses = data["clauses"]
            self._tokenized_corpus = data["tokenized_corpus"]
            if self._tokenized_corpus:
                self._bm25 = BM25Okapi(self._tokenized_corpus)
                self._indices[doc_id] = (self._clauses, self._tokenized_corpus, self._bm25)
            self._doc_id = doc_id
            self._dirty = False
            logger.info(f"BM25 index loaded: {path} ({len(self._clauses)} clauses)")
            return True
        except Exception as e:
            logger.warning(f"Failed to load BM25 index: {e}")
            return False


bm25_retriever = BM25Retriever()
