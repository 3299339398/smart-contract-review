"""Evaluation runner — runs test cases through agent nodes and scores results.

Supports two modes:
  1. quick: only risk_type_identify (fast, tests classification)
  2. full: risk_type → severity → compliance (full pipeline, requires more LLM calls)
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from eval.test_cases import TEST_CASES
from eval.scorer import EvalResult, build_report, llm_as_judge

logger = logging.getLogger(__name__)

# ── Unicode-safe markers for Windows GBK terminals ─────────────────────
_CHECK = "[PASS]"
_CROSS = "[FAIL]"


def _build_minimal_state(clause_text: str, review_type: str = "FULL") -> dict:
    """Build a minimal AgentState-like dict for running individual nodes."""
    return {
        "document_text": clause_text,
        "review_type": review_type,
        "task_id": "eval-runner",
        "contract_type": "GENERAL",
        "parsed_text": clause_text,
        "clauses": [{"index": 0, "text": clause_text}],
        "current_clause_index": 0,
        "total_clauses": 1,
        "all_risks": [],
        "overall_score": 0.0,
        "summary": "",
        "recommendations": [],
        "error": "",
        "should_continue": True,
    }


async def run_single_case_quick(case: dict) -> EvalResult:
    """Run risk_type_identify only (fast mode)."""
    from app.agent.nodes.risk_type_identify_node import risk_type_identify_node

    state = _build_minimal_state(case["clause_text"])
    result_state = await risk_type_identify_node(state)

    clause = result_state["clauses"][0]
    predicted_type = clause.get("risk_type", "NONE")
    predicted_reasoning = clause.get("reasoning_risk_type", "")

    # Quick severity estimate based on predicted risk type
    predicted_level = "MEDIUM"  # default
    if predicted_type != "NONE":
        predicted_level = "HIGH"  # conservative default for detected risks

    return EvalResult(
        case_id=case["id"],
        expected_risk_type=case["expected_risk_type"],
        predicted_risk_type=predicted_type,
        expected_risk_level=case["expected_risk_level"],
        predicted_risk_level=predicted_level,
        risk_type_match=predicted_type == case["expected_risk_type"],
        risk_level_match=predicted_level == case["expected_risk_level"],
        predicted_reasoning=predicted_reasoning,
    )


async def run_single_case_full(case: dict) -> EvalResult:
    """Run risk_type_identify + severity_check (full mode)."""
    from app.agent.nodes.risk_type_identify_node import risk_type_identify_node
    from app.agent.nodes.severity_check_node import severity_check_node

    state = _build_minimal_state(case["clause_text"])

    # Step 1: Risk type identification
    state = await risk_type_identify_node(state)
    clause = state["clauses"][0]
    predicted_type = clause.get("risk_type", "NONE")
    predicted_reasoning = clause.get("reasoning_risk_type", "")

    # Step 2: Severity check (only if risk detected)
    if predicted_type != "NONE":
        try:
            state = await severity_check_node(state)
            clause = state["clauses"][0]
            predicted_level = clause.get("risk_level", "MEDIUM")
            # Append severity reasoning
            severity_reasoning = clause.get("reasoning_severity", "")
            if severity_reasoning:
                predicted_reasoning += "\n[Severity]: " + severity_reasoning
        except Exception as e:
            logger.warning(f"Severity check failed for case {case['id']}: {e}")
            predicted_level = "MEDIUM"
    else:
        predicted_level = "LOW"

    return EvalResult(
        case_id=case["id"],
        expected_risk_type=case["expected_risk_type"],
        predicted_risk_type=predicted_type,
        expected_risk_level=case["expected_risk_level"],
        predicted_risk_level=predicted_level,
        risk_type_match=predicted_type == case["expected_risk_type"],
        risk_level_match=predicted_level == case["expected_risk_level"],
        predicted_reasoning=predicted_reasoning,
    )


async def run_all_cases(mode: str = "quick", with_llm_judge: bool = True) -> list[EvalResult]:
    """Run all test cases and return results."""
    results = []
    run_fn = run_single_case_full if mode == "full" else run_single_case_quick

    print(f"\n{'='*60}")
    print(f"  合同审查 Agent 评测")
    print(f"  模式: {mode.upper()}")
    print(f"  用例数: {len(TEST_CASES)}")
    print(f"  LLM-as-Judge: {'ON' if with_llm_judge else 'OFF'}")
    print(f"{'='*60}\n")

    for i, case in enumerate(TEST_CASES):
        case_start = time.time()
        print(f"  [{i+1}/{len(TEST_CASES)}] 用例 #{case['id']}: {case['description'][:60]}...", end=" ", flush=True)

        try:
            result = await run_fn(case)
            elapsed = time.time() - case_start

            # LLM-as-Judge
            if with_llm_judge:
                judge_score, judge_reasoning = await llm_as_judge(
                    clause_text=case["clause_text"],
                    expected_risk_type=case["expected_risk_type"],
                    expected_risk_level=case["expected_risk_level"],
                    predicted_risk_type=result.predicted_risk_type,
                    predicted_risk_level=result.predicted_risk_level,
                    predicted_reasoning=result.predicted_reasoning,
                )
                result.llm_judge_score = judge_score
                result.llm_judge_reasoning = judge_reasoning

            match_mark = _CHECK if result.risk_type_match else _CROSS
            print(f"{match_mark} 预测={result.predicted_risk_type} ({elapsed:.1f}s)")
            results.append(result)

        except Exception as e:
            logger.error(f"Case {case['id']} failed: {e}")
            print(f"ERROR: {e}")
            results.append(EvalResult(
                case_id=case["id"],
                expected_risk_type=case["expected_risk_type"],
                predicted_risk_type="ERROR",
                expected_risk_level=case["expected_risk_level"],
                predicted_risk_level="ERROR",
                risk_type_match=False,
                risk_level_match=False,
                predicted_reasoning=str(e),
            ))

    return results


def print_detailed_report(results: list[EvalResult]) -> None:
    """Print per-case results table."""
    print(f"\n{'─'*100}")
    print(f"  {'ID':<4} {'期望风险类型':<30} {'预测风险类型':<30} {'类型':<6} {'等级':<6} {'Judge':<6}")
    print(f"{'─'*100}")

    for r in results:
        print(
            f"  {r.case_id:<4} "
            f"{r.expected_risk_type:<30} "
            f"{r.predicted_risk_type:<30} "
            f"{_CHECK if r.risk_type_match else _CROSS:<6} "
            f"{_CHECK if r.risk_level_match else _CROSS:<6} "
            f"{r.llm_judge_score:.2f}"
        )

    print(f"{'─'*100}")

    # Print report
    report = build_report(results)
    print(report.summary())

    # Detailed LLM-as-Judge feedback for failed cases
    failed = [r for r in results if not r.risk_type_match]
    if failed:
        print(f"\n  详细分析（预测错误的用例）：")
        for r in failed:
            print(f"  ┌─ 用例 #{r.case_id}")
            print(f"  ├─ 期望: {r.expected_risk_type} / {r.expected_risk_level}")
            print(f"  ├─ 预测: {r.predicted_risk_type} / {r.predicted_risk_level}")
            if r.llm_judge_reasoning:
                print(f"  └─ Judge评语: {r.llm_judge_reasoning}")
            print()


def export_report_json(results: list[EvalResult], path: str = "eval_report.json") -> None:
    """Export results as JSON for CI/CD integration."""
    report = build_report(results)
    data = {
        "summary": {
            "total_cases": report.total_cases,
            "risk_type_precision": report.risk_type_precision,
            "risk_type_recall": report.risk_type_recall,
            "risk_type_f1": report.risk_type_f1,
            "risk_level_accuracy": report.risk_level_accuracy,
            "avg_llm_judge_score": report.avg_llm_judge_score,
        },
        "details": [
            {
                "case_id": r.case_id,
                "expected_risk_type": r.expected_risk_type,
                "predicted_risk_type": r.predicted_risk_type,
                "risk_type_match": r.risk_type_match,
                "risk_level_match": r.risk_level_match,
                "llm_judge_score": r.llm_judge_score,
                "llm_judge_reasoning": r.llm_judge_reasoning,
            }
            for r in results
        ],
    }
    out_path = Path(path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n  评测报告已导出: {out_path.resolve()}")
