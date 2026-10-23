"""LLM Provider 抽象层 —— 将 agent 节点与具体 LLM 后端解耦。

支持: DeepSeek（默认）、OpenAI、本地模型。
切换方式: 修改 config 中的 LLM_PROVIDER 或环境变量。

全部异步 —— 使用 openai.AsyncOpenAI，释放事件循环给其他请求。
"""

import re
import json
import logging
from abc import ABC, abstractmethod
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """LLM Provider 抽象接口。所有方法为异步。"""

    @abstractmethod
    async def chat(self, system_prompt: str, user_prompt: str,
                   temperature: float = 0.3, max_tokens: int = 2048) -> str:
        ...

    @abstractmethod
    async def chat_json(self, system_prompt: str, user_prompt: str,
                        temperature: float = 0.1, max_tokens: int = 4096) -> str:
        ...

    @abstractmethod
    async def chat_with_cot(self, system_prompt: str, user_prompt: str,
                            steps: list[str], output_format: str,
                            temperature: float = 0.3, max_tokens: int = 4096) -> tuple[str, str]:
        ...


class DeepSeekProvider(BaseLLMProvider):
    """DeepSeek API Provider（兼容 OpenAI 协议，异步）。"""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.deepseek_api_key or settings.openai_api_key,
            base_url=settings.deepseek_base_url,
        )
        self.model = settings.deepseek_model

    async def _call_api(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            raise

    async def chat(self, system_prompt: str, user_prompt: str,
                   temperature: float = 0.3, max_tokens: int = 2048) -> str:
        from app.cache import cache_manager
        cache_key = _make_cache_key("llm", system_prompt, user_prompt, str(temperature))

        cached = cache_manager.get(cache_key)
        if cached is not None:
            logger.debug(f"LLM 缓存命中: {cache_key[:32]}...")
            return cached

        result = await self._call_api([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], temperature, max_tokens)

        cache_manager.set(cache_key, result, settings.llm_cache_ttl)
        return result

    async def chat_json(self, system_prompt: str, user_prompt: str,
                        temperature: float = 0.1, max_tokens: int = 4096) -> str:
        json_hint = f"{system_prompt}\n\n重要：请仅返回合法的 JSON 格式，不要包含 markdown 标记或多余文本。"
        return await self.chat(json_hint, user_prompt, temperature, max_tokens)

    async def chat_with_cot(self, system_prompt: str, user_prompt: str,
                            steps: list[str], output_format: str,
                            temperature: float = 0.3, max_tokens: int = 4096) -> tuple[str, str]:
        from app.cache import cache_manager
        steps_key = "|".join(steps)
        cache_key = _make_cache_key("llm_cot", system_prompt, user_prompt, steps_key)

        cached = cache_manager.get(cache_key)
        if cached is not None:
            logger.debug(f"LLM CoT 缓存命中: {cache_key[:32]}...")
            parts = cached.split("\x00COT_SEP\x00", 1)
            if len(parts) == 2:
                return parts[0], parts[1]

        steps_text = "\n".join(f"  {i+1}. {step}" for i, step in enumerate(steps))
        cot_prompt = f"""{system_prompt}

请按以下步骤逐步推理分析，不要跳过任何步骤：
{steps_text}

输出格式要求：
1. 先输出「推理过程」段落（用【推理过程】标记开头）
2. 再输出「最终答案」段落（用【最终答案】标记开头）
{output_format}

注意：必须在【最终答案】段落中给出符合格式的最终结果。"""

        response = await self.chat(cot_prompt, user_prompt, temperature, max_tokens)

        reasoning = ""
        answer = response
        answer_match = re.search(r'【最终答案】\s*\n?(.*)', response, re.DOTALL)
        reasoning_match = re.search(r'【推理过程】\s*\n?(.*?)(?:【最终答案】|$)', response, re.DOTALL)

        if answer_match:
            if reasoning_match:
                reasoning = reasoning_match.group(1).strip()
            else:
                reasoning = response[:response.index("【最终答案】")].strip()
                if reasoning.startswith("【推理过程】"):
                    reasoning = reasoning[len("【推理过程】"):].strip()
            answer = answer_match.group(1).strip()
        elif reasoning_match:
            reasoning = reasoning_match.group(1).strip()

        cache_manager.set(cache_key, f"{reasoning}\x00COT_SEP\x00{answer}", settings.llm_cache_ttl)
        return reasoning, answer


class LLMProviderFactory:
    _providers: dict[str, type[BaseLLMProvider]] = {
        "deepseek": DeepSeekProvider,
    }

    @classmethod
    def register(cls, name: str, provider_cls: type[BaseLLMProvider]):
        cls._providers[name] = provider_cls

    @classmethod
    def create(cls, provider_name: str = None) -> BaseLLMProvider:
        name = provider_name or settings.llm_provider
        if name not in cls._providers:
            logger.warning(f"未知的 LLM Provider '{name}'，降级为 deepseek")
            name = "deepseek"
        return cls._providers[name]()


def _make_cache_key(*args: str) -> str:
    import hashlib
    combined = "|".join(args)
    return hashlib.sha256(combined.encode()).hexdigest()[:48]
