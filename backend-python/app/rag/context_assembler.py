"""上下文组装器 —— 为 LLM 构建 Prompt 上下文。

智能地将检索到的条款打包到 LLM 上下文中：
  - 按相关性分数排序（rerank_score 优先于 hybrid_score）
  - 添加带条款序号和相关性分数的元数据头
  - 在句子边界截断过长条款
  - token 预算耗尽时停止打包
  - 记录截断和丢弃数量用于日志
"""

import logging
from typing import List, Dict
from dataclasses import dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class AssembledContext:
    prompt_text: str
    included_indices: List[int] = field(default_factory=list)
    total_tokens_estimate: int = 0
    truncated_count: int = 0
    omitted_count: int = 0


class ContextAssembler:
    """将检索到的条款打包到受 token 预算约束的 LLM 上下文中。"""

    def __init__(self, max_tokens: int = None):
        self._max_tokens = max_tokens or settings.rag_context_max_tokens
        self._max_clause_chars = settings.rag_context_clause_max_chars
        self._chars_per_token = 1.5  # 中英文混合保守估算比例

    def assemble(self, results: List[Dict], question: str,
                 system_prompt: str = "") -> AssembledContext:
        """将排序后的检索结果打包为上下文字符串，遵守 token 预算。

        Args:
            results: 带分数的检索条款（调用前已按分数排序）
            question: 用户问题
            system_prompt: 系统提示词（用于 token 预算计算）
        """
        if not results:
            return AssembledContext(prompt_text="(未检索到相关条款)")

        # 预留问题、系统提示词和模板开销的 token
        template_overhead = 200
        reserved = (
            self.estimate_tokens(question) +
            self.estimate_tokens(system_prompt) +
            template_overhead
        )
        budget = max(500, self._max_tokens - reserved)

        parts = []
        included = []
        truncated = 0
        token_used = 0

        # 排序：rerank_score 优先于 hybrid_score
        sorted_results = sorted(
            results,
            key=lambda r: r.get("rerank_score", r.get("hybrid_score", 0)),
            reverse=True,
        )

        for i, r in enumerate(sorted_results):
            idx = r.get("clause_index", "?")
            text = r.get("text", "")
            score = r.get("rerank_score", r.get("hybrid_score", 0))

            if not text:
                continue

            # 截断过长条款
            truncated_text = self._truncate_clause(text)
            if len(truncated_text) < len(text):
                truncated += 1

            # 格式化元数据头
            header = f"【第{idx}条 | 相关性: {score:.2f}】"
            block = f"{header}\n{truncated_text}"

            block_tokens = self.estimate_tokens(block)
            if token_used + block_tokens > budget:
                break

            parts.append(block)
            included.append(idx)
            token_used += block_tokens

        omitted = len(results) - len(parts)

        if omitted > 0:
            logger.debug(f"Context assembly: {len(parts)}/{len(results)} clauses packed, "
                         f"{truncated} truncated, {omitted} omitted, "
                         f"tokens ~{token_used}/{budget}")

        prompt_text = "\n\n".join(parts) if parts else "(检索结果因长度限制被截断)"

        return AssembledContext(
            prompt_text=prompt_text,
            included_indices=included,
            total_tokens_estimate=token_used,
            truncated_count=truncated,
            omitted_count=omitted,
        )

    # ── 内部方法 ─────────────────────────────────────────────────────────

    def estimate_tokens(self, text: str) -> int:
        """中英文混合文本的保守 token 估算。"""
        if not text:
            return 0
        return int(len(text) / self._chars_per_token)

    def _truncate_clause(self, text: str) -> str:
        """使用头+尾策略截断至最大字符数，保留条款尾部关键信息。"""
        from app.utils.text_utils import truncate_head_tail
        return truncate_head_tail(text, self._max_clause_chars, head_ratio=0.65)


context_assembler = ContextAssembler()
