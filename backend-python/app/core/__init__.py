"""核心抽象层 —— Provider 接口、工具注册中心。

本模块提供依赖反转层，将应用与具体的 LLM、Embedding、工具实现解耦。
"""

from app.core.llm_provider import BaseLLMProvider, DeepSeekProvider, LLMProviderFactory
from app.core.embedding_provider import (
    BaseEmbeddingProvider, SentenceTransformersProvider, EmbeddingProviderFactory,
)
from app.core.tool_registry import tool_registry, register_tool

__all__ = [
    "BaseLLMProvider", "DeepSeekProvider", "LLMProviderFactory",
    "BaseEmbeddingProvider", "SentenceTransformersProvider", "EmbeddingProviderFactory",
    "tool_registry", "register_tool",
]
