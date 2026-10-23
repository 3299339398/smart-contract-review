"""Evaluation CLI — command-line entry point for running the eval framework.

Usage:
  python -m eval.cli --all           # Run all cases (quick mode)
  python -m eval.cli --all --full    # Run all cases in full mode
  python -m eval.cli --case 1        # Run a single case
  python -m eval.cli --all --no-judge  # Skip LLM-as-Judge
  python -m eval.cli --all --export eval_report.json  # Export JSON report
"""

import argparse
import asyncio
import logging
import sys

# Force UTF-8 on Windows terminals
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.WARNING,  # Suppress debug logs from agent nodes
    format="%(levelname)s: %(message)s",
)


def main():
    parser = argparse.ArgumentParser(
        description="合同审查 Agent 评测框架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m eval.cli --all               # 运行全部用例（快速模式）
  python -m eval.cli --all --full        # 运行全部用例（完整模式）
  python -m eval.cli --case 3            # 仅运行第3个用例
  python -m eval.cli --all --no-judge    # 跳过 LLM-as-Judge
  python -m eval.cli --all --export report.json
        """,
    )
    parser.add_argument("--all", action="store_true", help="运行全部10个测试用例")
    parser.add_argument("--case", type=int, help="运行指定的单个用例 (1-10)")
    parser.add_argument("--full", action="store_true", help="完整模式 (含severity_check节点)")
    parser.add_argument("--no-judge", action="store_true", help="跳过 LLM-as-Judge 评分")
    parser.add_argument("--export", type=str, metavar="PATH", help="导出JSON报告路径")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细日志")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.all and not args.case:
        parser.print_help()
        return

    from eval.test_cases import TEST_CASES
    from eval.runner import (
        run_all_cases, run_single_case_quick, run_single_case_full,
        print_detailed_report, export_report_json,
    )
    from eval.scorer import EvalResult, build_report

    async def _run():
        if args.case:
            # Single case mode
            case = next((c for c in TEST_CASES if c["id"] == args.case), None)
            if not case:
                print(f"错误: 未找到用例 #{args.case} (有效范围: 1-{len(TEST_CASES)})")
                return

            print(f"\n  运行单个用例 #{case['id']}: {case['description']}")
            run_fn = run_single_case_full if args.full else run_single_case_quick
            result = await run_fn(case)

            if not args.no_judge:
                from eval.scorer import llm_as_judge
                score, reasoning = await llm_as_judge(
                    clause_text=case["clause_text"],
                    expected_risk_type=case["expected_risk_type"],
                    expected_risk_level=case["expected_risk_level"],
                    predicted_risk_type=result.predicted_risk_type,
                    predicted_risk_level=result.predicted_risk_level,
                    predicted_reasoning=result.predicted_reasoning,
                )
                result.llm_judge_score = score
                result.llm_judge_reasoning = reasoning

            print(f"\n  期望: {result.expected_risk_type} / {result.expected_risk_level}")
            print(f"  预测: {result.predicted_risk_type} / {result.predicted_risk_level}")
            print(f"  类型匹配: {'✓' if result.risk_type_match else '✗'}")
            print(f"  等级匹配: {'✓' if result.risk_level_match else '✗'}")
            if result.llm_judge_score:
                print(f"  LLM-Judge: {result.llm_judge_score:.2f}")
                print(f"  Judge评语: {result.llm_judge_reasoning}")
            if result.predicted_reasoning:
                print(f"\n  AI推理过程:\n  {result.predicted_reasoning[:500]}")
        else:
            # All cases mode
            mode = "full" if args.full else "quick"
            results = await run_all_cases(mode=mode, with_llm_judge=not args.no_judge)
            print_detailed_report(results)

            if args.export:
                export_report_json(results, args.export)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
