"""引用校验器 —— 检测 LLM 幻觉产生的虚假条款引用。

在 LLM 生成答案后，提取其中所有"第X条"引用并与检索结果交叉比对。
对检测到的幻觉内容在答案末尾追加警告标记。

这是法律领域应用的关键信任/安全功能，因为 LLM 经常会编造看似合理但
实际不存在的条款编号。
"""

import logging
import re
from typing import List, Dict
from dataclasses import dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)

# 中文数字字符映射表
_CN_NUMS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "百": 100, "千": 1000,
}


@dataclass
class CitationCheckResult:
    is_valid: bool
    cited_indices: List[int] = field(default_factory=list)
    found_in_context: List[int] = field(default_factory=list)
    hallucinated: List[int] = field(default_factory=list)
    warning_message: str = ""


class CitationVerifier:
    """生成后引用幻觉检测器。"""

    def __init__(self):
        # 匹配 "第X条"，X 可为中文或阿拉伯数字
        self._citation_pattern = re.compile(
            r'第\s*([一二三四五六七八九十百千\d]+)\s*条'
        )

    def verify(self, answer: str, retrieved_sources: List[Dict]) -> CitationCheckResult:
        """提取答案中的条款引用编号并与检索上下文交叉比对。

        Args:
            answer: LLM 生成的回答文本
            retrieved_sources: 实际检索并展示给 LLM 的条款列表
        """
        if not settings.rag_citation_verify_enabled:
            return CitationCheckResult(is_valid=True, warning_message="")

        cited = self._extract_indices(answer)

        if not cited:
            return CitationCheckResult(is_valid=True)

        valid_indices = {
            s.get("clause_index") for s in retrieved_sources
        }

        found = [i for i in cited if i in valid_indices]
        hallucinated = [i for i in cited if i not in valid_indices]

        if hallucinated:
            msg = (
                f"⚠️ 请注意：回答中引用了检索结果中不存在的条款编号"
                f"（{hallucinated}），这些引用可能不准确，建议核实后再作判断。"
            )
        else:
            msg = ""

        if hallucinated:
            logger.warning(
                f"Citation hallucination detected: cited={cited}, "
                f"found={found}, hallucinated={hallucinated}"
            )

        return CitationCheckResult(
            is_valid=len(hallucinated) == 0,
            cited_indices=cited,
            found_in_context=found,
            hallucinated=hallucinated,
            warning_message=msg,
        )

    # ── 内部方法 ─────────────────────────────────────────────────────────

    def _extract_indices(self, text: str) -> List[int]:
        """从文本中提取所有"第X条"引用中的条款编号。"""
        matches = re.finditer(self._citation_pattern, text)
        indices = []
        for m in matches:
            raw = m.group(1).strip()
            try:
                if raw.isdigit():
                    indices.append(int(raw))
                else:
                    indices.append(self._cn_to_int(raw))
            except ValueError:
                continue
        return list(dict.fromkeys(indices))  # 去重并保持原始顺序

    @staticmethod
    def _cn_to_int(cn: str) -> int:
        """将中文数字字符串转换为整数。"""
        # 处理简单情况：十一 → 11, 二十五 → 25
        total = 0
        unit = 1
        for ch in reversed(cn):
            if ch in ("十", "百", "千"):
                unit = _CN_NUMS[ch]
            else:
                val = _CN_NUMS.get(ch, 0)
                total += val * unit
                unit = 1

        # 处理 "十" 单独出现等特殊情况
        if cn[0] == "十" and total == 0:
            total = 10
        elif cn.endswith("十"):
            total = total * 10

        return total if total > 0 else 0


citation_verifier = CitationVerifier()
