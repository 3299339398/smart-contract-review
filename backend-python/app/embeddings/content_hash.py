"""条款去重的内容哈希。

对条款文本计算 SHA256 哈希，实现跨文档去重。
供向量存储使用，避免对相同条款重复计算 Embedding。
"""

import hashlib


def clause_hash(text: str) -> str:
    """对归一化后的条款文本计算 SHA256 哈希，用于去重。"""
    normalized = text.strip().lower()
    normalized = " ".join(normalized.split())  # 合并多余空白
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_duplicate(text: str, known_hashes: set[str]) -> bool:
    """检查条款文本是否已被索引。"""
    return clause_hash(text) in known_hashes
