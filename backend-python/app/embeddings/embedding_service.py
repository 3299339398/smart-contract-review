"""Embedding 服务 —— 基于配置的 Embedding Provider 薄包装层。

委托给 EmbeddingProviderFactory 做实际的向量计算。
现有引用 `embedding_service` 的代码保持兼容，无需修改。
"""

import logging
from typing import List
from app.core.embedding_provider import EmbeddingProviderFactory

logger = logging.getLogger(__name__)


class EmbeddingService:
    """兼容包装器，委托给已配置的 Embedding Provider 执行向量计算。"""

    _instance: "EmbeddingService | None" = None

    def __init__(self):
        self._provider = None

    @property
    def provider(self):
        if self._provider is None:
            self._provider = EmbeddingProviderFactory.create()
        return self._provider

    @property
    def model(self):
        """向后兼容：返回底层模型，供直接访问。"""
        return self.provider

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return await self.provider.embed_texts(texts)

    async def embed_query(self, query: str) -> List[float]:
        return await self.provider.embed_query(query)


embedding_service = EmbeddingService()
