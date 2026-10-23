"""LLM 客户端 —— 对 Provider 工厂的薄兼容层。

现有代码统一从本模块导入 llm_client。本模块委托给配置的 Provider，
agent 各节点无需感知底层 Provider 切换。全部异步。
"""

from app.core.llm_provider import LLMProviderFactory


class LlmClient:
    """兼容包装器，委托给配置的 LLM Provider。"""

    def __init__(self):
        self._provider = None

    @property
    def provider(self):
        if self._provider is None:
            self._provider = LLMProviderFactory.create()
        return self._provider

    async def chat(self, system_prompt: str, user_prompt: str,
                   temperature: float = 0.3, max_tokens: int = 2048) -> str:
        return await self.provider.chat(system_prompt, user_prompt, temperature, max_tokens)

    async def chat_json(self, system_prompt: str, user_prompt: str,
                        temperature: float = 0.1, max_tokens: int = 4096) -> str:
        return await self.provider.chat_json(system_prompt, user_prompt, temperature, max_tokens)

    async def chat_with_cot(self, system_prompt: str, user_prompt: str,
                            steps: list[str], output_format: str,
                            temperature: float = 0.3, max_tokens: int = 4096) -> tuple[str, str]:
        return await self.provider.chat_with_cot(
            system_prompt, user_prompt, steps, output_format, temperature, max_tokens
        )


llm_client = LlmClient()
