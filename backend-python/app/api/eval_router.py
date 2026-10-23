"""评测 API 路由 — 触发评测、查询历史报告、SSE 实时进度。"""

import asyncio
import datetime
import json
import uuid
import re
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.common import ApiResponse
from app.schemas.eval import (
    EvalRunRequest, EvalRunResponse, EvalReportResponse, EvalCaseDetail,
)
from app.middleware.auth_middleware import get_current_user_id
from app.services.rate_limit_service import rate_limit, RateLimitExceededException

router = APIRouter(tags=["eval"])

# 评测报告持久化目录
_REPORT_DIR = Path(__file__).parent.parent.parent / "data" / "eval_reports"
_REPORT_DIR.mkdir(parents=True, exist_ok=True)

# 内存中的运行状态
_running_tasks: dict[str, dict] = {}

# SSE 订阅者
_subscribers: dict[str, list[asyncio.Queue]] = {}
_REPORT_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _report_path(report_id: str) -> Path:
    if not _REPORT_ID_RE.fullmatch(report_id):
        raise HTTPException(status_code=404, detail="报告不存在")
    path = (_REPORT_DIR / f"{report_id}.json").resolve()
    if path.parent != _REPORT_DIR.resolve():
        raise HTTPException(status_code=404, detail="报告不存在")
    return path


def _subscribe(report_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    if report_id not in _subscribers:
        _subscribers[report_id] = []
    _subscribers[report_id].append(q)
    return q


def _publish(report_id: str, event: dict):
    for q in _subscribers.get(report_id, []):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def _unsubscribe(report_id: str, q: asyncio.Queue):
    subs = _subscribers.get(report_id, [])
    if q in subs:
        subs.remove(q)


async def _run_eval_task(report_id: str, user_id: int, mode: str, with_llm_judge: bool):
    """后台执行评测任务，通过 SSE 推送进度。"""
    from eval.test_cases import TEST_CASES
    from eval.runner import run_single_case_quick, run_single_case_full
    from eval.scorer import EvalResult, build_report, llm_as_judge
    import time

    _running_tasks[report_id] = {"status": "running", "user_id": user_id}
    _publish(report_id, {"event": "EVAL_STARTED", "totalCases": len(TEST_CASES), "mode": mode})

    results: list = []
    run_fn = run_single_case_full if mode == "full" else run_single_case_quick
    total = len(TEST_CASES)

    for i, case in enumerate(TEST_CASES):
        case_start = time.time()
        _publish(report_id, {
            "event": "CASE_STARTED",
            "caseIndex": i + 1,
            "totalCases": total,
            "caseId": case["id"],
            "description": case["description"],
        })

        try:
            result = await run_fn(case)
            elapsed = time.time() - case_start

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

            results.append(result)
            _publish(report_id, {
                "event": "CASE_COMPLETED",
                "caseIndex": i + 1,
                "caseId": case["id"],
                "riskTypeMatch": result.risk_type_match,
                "riskLevelMatch": result.risk_level_match,
                "predictedRiskType": result.predicted_risk_type,
                "predictedRiskLevel": result.predicted_risk_level,
                "elapsed": round(elapsed, 1),
            })

        except Exception as e:
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
            _publish(report_id, {
                "event": "CASE_ERROR",
                "caseIndex": i + 1,
                "caseId": case["id"],
                "error": str(e),
            })

    # 生成报告
    report = build_report(results)
    report_data = {
        "reportId": report_id,
        "userId": user_id,
        "mode": mode,
        "totalCases": report.total_cases,
        "riskTypePrecision": report.risk_type_precision,
        "riskTypeRecall": report.risk_type_recall,
        "riskTypeF1": report.risk_type_f1,
        "riskLevelAccuracy": report.risk_level_accuracy,
        "avgLlmJudgeScore": report.avg_llm_judge_score,
        "details": [
            {
                "caseId": r.case_id,
                "description": TEST_CASES[r.case_id - 1]["description"],
                "expectedRiskType": r.expected_risk_type,
                "expectedRiskLevel": r.expected_risk_level,
                "predictedRiskType": r.predicted_risk_type,
                "predictedRiskLevel": r.predicted_risk_level,
                "riskTypeMatch": r.risk_type_match,
                "riskLevelMatch": r.risk_level_match,
                "llmJudgeScore": r.llm_judge_score,
                "llmJudgeReasoning": r.llm_judge_reasoning,
                "predictedReasoning": r.predicted_reasoning,
            }
            for r in results
        ],
        "createdAt": datetime.datetime.utcnow().isoformat(),
    }

    # 持久化到磁盘
    report_path = _report_path(report_id)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    _running_tasks[report_id] = {"status": "completed", "user_id": user_id, "report": report_data}
    _publish(report_id, {"event": "EVAL_COMPLETED", "report": report_data})


@router.post("/run", response_model=ApiResponse)
async def start_eval(
    body: EvalRunRequest,
    user_id: int = Depends(get_current_user_id),
):
    """启动一次评测任务。"""
    try:
        rate_limit(user_id, "eval:run", max_requests=3, window_seconds=60)
    except RateLimitExceededException as e:
        raise HTTPException(status_code=429, detail=str(e))
    active = sum(
        1 for task in _running_tasks.values()
        if task.get("user_id") == user_id and task.get("status") == "running"
    )
    if active >= 2:
        raise HTTPException(status_code=429, detail="评测任务并发数已达上限")
    report_id = uuid.uuid4().hex
    mode = body.mode if body.mode in ("quick", "full") else "quick"

    _running_tasks[report_id] = {"status": "queued", "user_id": user_id}
    asyncio.create_task(_run_eval_task(report_id, user_id, mode, body.withLlmJudge))

    return ApiResponse(
        code=200,
        message="评测已启动",
        data={"reportId": report_id, "status": "running"},
    )


@router.get("/reports", response_model=ApiResponse)
async def list_reports(user_id: int = Depends(get_current_user_id)):
    """列出所有历史评测报告（按时间倒序）。"""
    reports = []
    for path in sorted(_REPORT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("userId") != user_id:
                continue
            reports.append({
                "reportId": data["reportId"],
                "mode": data["mode"],
                "totalCases": data["totalCases"],
                "riskTypeF1": data["riskTypeF1"],
                "avgLlmJudgeScore": data["avgLlmJudgeScore"],
                "createdAt": data["createdAt"],
            })
        except Exception:
            continue
    return ApiResponse(code=200, data={"content": reports, "totalElements": len(reports)})


@router.get("/reports/{report_id}", response_model=ApiResponse)
async def get_report(
    report_id: str,
    user_id: int = Depends(get_current_user_id),
):
    """获取指定评测报告的完整详情。"""
    # 先查内存中的运行中报告
    if report_id in _running_tasks:
        task = _running_tasks[report_id]
        if task.get("user_id") != user_id:
            raise HTTPException(status_code=404, detail="报告不存在")
        if task["status"] == "completed":
            return ApiResponse(code=200, data=task["report"])
        else:
            return ApiResponse(code=200, data={"reportId": report_id, "status": "running"})

    # 从磁盘加载
    report_path = _report_path(report_id)
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="报告不存在")

    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("userId") != user_id:
        raise HTTPException(status_code=404, detail="报告不存在")
    return ApiResponse(code=200, data=data)


@router.get("/reports/{report_id}/stream")
async def stream_eval(
    report_id: str,
    user_id: int = Depends(get_current_user_id),
):
    """SSE 实时推送评测进度。"""
    if report_id in _running_tasks:
        if _running_tasks[report_id].get("user_id") != user_id:
            raise HTTPException(status_code=404, detail="报告不存在")
    else:
        report_path = _report_path(report_id)
        if not report_path.exists():
            raise HTTPException(status_code=404, detail="报告不存在")
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                if json.load(f).get("userId") != user_id:
                    raise HTTPException(status_code=404, detail="报告不存在")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=404, detail="报告不存在")
    async def event_generator():
        q = _subscribe(report_id)
        try:
            # 如果任务已在运行中，先回放当前状态
            if report_id in _running_tasks:
                task = _running_tasks[report_id]
                if task["status"] == "completed":
                    yield f"data: {json.dumps({'event': 'EVAL_COMPLETED', 'report': task['report']}, ensure_ascii=False)}\n\n"
                    return

            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("event") == "EVAL_COMPLETED":
                        break
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _unsubscribe(report_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
