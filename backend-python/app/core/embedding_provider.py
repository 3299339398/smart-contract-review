"""Embedding Provider 抽象层 —— 将应用与具体嵌入模型后端解耦。

支持：sentence-transformers（默认，本地运行）、OpenAI embeddings（API 调用）。
切换方式：修改 config 中的 EMBEDDING_PROVIDER 或环境变量。
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import List
from app.config import settings

logger = logging.getLogger(__name__)


class BaseEmbeddingProvider(ABC):
    """Embedding Provider 抽象接口。"""

    @abstractmethod
    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """对文本列表进行向量化，返回 embedding 向量列表。"""
        ...

    @abstractmethod
    async def embed_query(self, query: str) -> List[float]:
        """对单条查询文本进行向量化，返回单个 embedding 向量。"""
        ...

    @abstractmethod
    def dimension(self) -> int:
        """返回 embedding 向量的维度。"""
        ...


class SentenceTransformersProvider(BaseEmbeddingProvider):
    """本地 sentence-transformers 模型（paraphrase-multilingual-MiniLM-L12-v2）。"""

    def __init__(self):
        if not os.environ.get("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

        from sentence_transformers import SentenceTransformer

        self._model_name = settings.embedding_model
        self._model: SentenceTransformer | None = None

    @property
    def model(self):
        if self._model is None:
            logger.info(f"Loading embedding model: {self._model_name}")
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            logger.info(f"Embedding model loaded, dim={self.dimension()}")
        return self._model

    def dimension(self) -> int:
        return self.model.get_sentence_embedding_dimension()

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return embeddings.tolist()

    async def embed_query(self, query: str) -> List[float]:
        embedding = self.model.encode(query, normalize_embeddings=True, show_progress_bar=False)
        return embedding.tolist()


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI 兼容的 embeddings API 提供商（DeepSeek、OpenAI 等）。

    使用 /v1/embeddings 端点。设置 EMBEDDING_PROVIDER=openai 并在环境变量中
    配置 OPENAI_API_KEY / OPENAI_BASE_URL。
    """

    def __init__(self):
        import os
        from openai import AsyncOpenAI

        api_key = settings.openai_api_key or settings.deepseek_api_key
        base_url = os.environ.get("OPENAI_BASE_URL", settings.deepseek_base_url)
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = os.environ.get("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
        self._dim = None

    def dimension(self) -> int:
        if self._dim is None:
            self._dim = 1536  # text-embedding-3-small 的默认维度
        return self._dim

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        try:
            resp = await self.client.embeddings.create(model=self._model, input=texts)
            self._dim = len(resp.data[0].embedding)
            return [d.embedding for d in resp.data]
        except Exception as e:
            logger.error(f"Embedding API error: {e}")
            raise

    async def embed_query(self, query: str) -> list[float]:
        embeddings = await self.embed_texts([query])
        return embeddings[0]


class EmbeddingProviderFactory:
    """根据配置创建 embedding provider 的工厂类。"""

    _providers: dict[str, type[BaseEmbeddingProvider]] = {
        "sentence_transformers": SentenceTransformersProvider,
        "openai": OpenAIEmbeddingProvider,
    }

    @classmethod
    def register(cls, name: str, provider_cls: type[BaseEmbeddingProvider]):
        """注册一个新的 embedding provider 类型。"""
        cls._providers[name] = provider_cls

    @classmethod
    def create(cls, provider_name: str = None) -> BaseEmbeddingProvider:
        """按名称创建 embedding provider 实例。"""
        name = provider_name or settings.embedding_provider
        if name not in cls._providers:
            logger.warning(f"Unknown embedding provider '{name}', falling back to sentence_transformers")
            name = "sentence_transformers"
        return cls._providers[name]()
