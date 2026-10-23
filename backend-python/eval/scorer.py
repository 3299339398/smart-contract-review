"""Evaluation scorer — exact match metrics + LLM-as-Judge.

Two scoring approaches:
  1. Exact match: precision/recall/F1 on risk_type and risk_level
  2. LLM-as-Judge: qualitative assessment of whether the review output
     captures the expected findings (more nuanced, catches partial matches)
"""

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    case_id: int
    expected_risk_type: str
    predicted_risk_type: str
    expected_risk_level: str
    predicted_risk_level: str
    risk_type_match: bool
    risk_level_match: bool
    llm_judge_score: float = 0.0
    llm_judge_reasoning: str = ""
    predicted_reasoning: str = ""


@dataclass
class EvalReport:
    results: list[EvalResult] = field(default_factory=list)
    total_cases: int = 0
    risk_type_precision: float = 0.0
    risk_type_recall: float = 0.0
    risk_type_f1: float = 0.0
    risk_level_accuracy: float = 0.0
    avg_llm_judge_score: float = 0.0

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "  合同审查 Agent 评测报告",
            "=" * 60,
            f"  测试用例数:       {self.total_cases}",
            f"  风险类型 Precision: {self.risk_type_precision:.1%}",
            f"  风险类型 Recall:    {self.risk_type_recall:.1%}",
            f"  风险类型 F1:        {self.risk_type_f1:.1%}",
            f"  风险等级准确率:     {self.risk_level_accuracy:.1%}",
            f"  LLM-as-Judge 均分:  {self.avg_llm_judge_score:.2f}/1.00",
            "=" * 60,
        ]
        return "\n".join(lines)


def compute_exact_metrics(results: list[EvalResult]) -> tuple[float, float, float]:
    """Compute precision, recall, F1 for risk_type classification.

    Precision: of all predicted risks, how many were correct?
    Recall: of all expected risks, how many were correctly identified?
    """
    tp = sum(1 for r in results if r.risk_type_match)
    fp = sum(1 for r in results if not r.risk_type_match and r.predicted_risk_type != "NONE")
    fn = sum(1 for r in results if not r.risk_type_match and r.expected_risk_type != "NONE")

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return precision, recall, f1


def compute_level_accuracy(results: list[EvalResult]) -> float:
    """Compute accuracy of risk_level prediction."""
    if not results:
        return 0.0
    correct = sum(1 for r in results if r.risk_level_match)
    return correct / len(results)


LLM_JUDGE_PROMPT = """你是一位资深合同审查专家。你的任务是评估 AI 合同审查系统的输出质量。

对于每个测试用例，你会看到：
- 条款原文
- 期望的风险类型和风险等级
- AI 系统的实际输出（风险类型 + 风险等级 + 推理过程）

请从以下维度评分（0-100）：
1. 风险类型判断是否合理（即使与期望不同，如果有道理也应给分）
2. 风险等级判定是否恰当
3. 是否捕捉到了条款中的核心风险点
4. 推理过程是否逻辑清晰

输出格式（JSON）：
{"score": 85, "reasoning": "评分理由（100字以内）"}

评分参考：
- 90-100: 完全正确，推理优秀
- 70-89: 基本正确，风险类型或等级有细微偏差
- 50-69: 部分正确，识别到了风险但分类有误
- 30-49: 发现了问题但分析方向错误
- 0-29: 完全未识别到风险或严重误判"""


async def llm_as_judge(
    clause_text: str,
    expected_risk_type: str,
    expected_risk_level: str,
    predicted_risk_type: str,
    predicted_risk_level: str,
    predicted_reasoning: str,
) -> tuple[float, str]:
    """Use LLM to judge the quality of a single prediction."""
    try:
        from app.llm.client import llm_client

        prompt = f"""条款原文：
{clause_text[:500]}

期望输出：风险类型={expected_risk_type}, 风险等级={expected_risk_level}

AI 系统输出：
风险类型={predicted_risk_type}, 风险等级={predicted_risk_level}
推理过程：{predicted_reasoning[:300] if predicted_reasoning else '无'}

请对 AI 系统的输出质量进行评分。"""

        response = llm_client.chat_json(LLM_JUDGE_PROMPT, prompt, temperature=0.1, max_tokens=1024)
        response = response.strip()
        if response.startswith("```"):
            response = response.split("\n", 1)[1].rsplit("\n", 1)[0]

        result = json.loads(response)
        score = result.get("score", 50) / 100.0
        reasoning = result.get("reasoning", "")
        return max(0.0, min(1.0, score)), reasoning

    except Exception as e:
        logger.warning(f"LLM-as-Judge failed: {e}")
        # Fallback: give partial credit based on risk_level match
        if predicted_risk_type == expected_risk_type:
            return 0.9, "Fallback: exact type match"
        elif predicted_risk_level == expected_risk_level:
            return 0.5, "Fallback: level match only"
        elif predicted_risk_type != "NONE" and expected_risk_type != "NONE":
            return 0.3, "Fallback: at least found a risk"
        return 0.1, "Fallback: missed the risk"


def build_report(results: list[EvalResult]) -> EvalReport:
    """Build a full evaluation report from individual results."""
    report = EvalReport(results=results, total_cases=len(results))

    if results:
        p, r, f1 = compute_exact_metrics(results)
        report.risk_type_precision = p
        report.risk_type_recall = r
        report.risk_type_f1 = f1
        report.risk_level_accuracy = compute_level_accuracy(results)
        report.avg_llm_judge_score = (
            sum(r.llm_judge_score for r in results) / len(results)
        )

    return report
