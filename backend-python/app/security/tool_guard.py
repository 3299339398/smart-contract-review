"""第 3 层：MCP 工具调用守卫 —— 输入/输出校验。

包装 MCP 工具调用，提供：
- 执行前校验输入参数
- 执行后扫描输出中的异常
- 记录每次工具调用以供审计追踪

在 agent 节点调用 MCP 工具时使用。
"""

import logging
from typing import Any, Callable, Coroutine
from app.security.rule_filter import INJECTION_PATTERNS, DANGEROUS_KEYWORDS
from app.security.schemas import GuardResult

logger = logging.getLogger(__name__)

# 各工具的参数长度限制
TOOL_PARAM_LIMITS = {
    "search_legal_regulations": {"query": 2000},
    "compare_with_template": {"clause_text": 5000},
    "generate_amendment": {"clause_text": 5000, "risk_description": 2000},
    "evaluate_contract_balance": {},  # 无字符串参数需要检查
}


def _scan_for_injection(text: str) -> bool:
    """快速扫描工具参数中的注入模式。"""
    import re
    for pattern, _ in INJECTION_PATTERNS:
        if re.search(pattern, text):
            return True
    for keyword, _ in DANGEROUS_KEYWORDS:
        if keyword.lower() in text.lower():
            return True
    return False


def _summarize(value: Any, max_len: int = 200) -> str:
    """生成值的简短摘要，用于审计日志。"""
    if value is None:
        return "None"
    if isinstance(value, str):
        return value[:max_len] + ("..." if len(value) > max_len else "")
    if isinstance(value, (list, tuple)):
        return f"[{len(value)} items]"
    if isinstance(value, dict):
        return f"{{{len(value)} keys}}"
    return str(value)[:max_len]


async def guard_tool_call(
    tool_name: str,
    handler: Callable[..., Coroutine],
    params: dict[str, Any],
    task_id: str = "",
    user_id: int | None = None,
) -> Any:
    """包装 MCP 工具调用，提供执行前/后校验。

    Args:
        tool_name: MCP 工具名称（如 "search_legal_regulations"）
        handler: 要调用的异步处理函数
        params: 参数名 → 值的字典
        task_id: 可选的任务 ID，用于上下文关联
        user_id: 可选的用户 ID，用于审计日志

    Returns:
        工具的返回值（Pydantic 模型或字典）
    """
    # ── 执行前校验 ─────────────────────────────────────────────────
    # 1. 检查参数长度限制
    limits = TOOL_PARAM_LIMITS.get(tool_name, {})
    for param_name, max_len in limits.items():
        if param_name in params and isinstance(params[param_name], str):
            if len(params[param_name]) > max_len:
                from app.utils.text_utils import truncate_head_tail
                logger.warning(
                    f"工具 {tool_name}: 参数 '{param_name}' 超限 "
                    f"({len(params[param_name])} > {max_len})，已头尾截断"
                )
                params[param_name] = truncate_head_tail(params[param_name], max_len)

    # 2. 扫描字符串参数中的注入尝试
    for param_name, value in params.items():
        if isinstance(value, str) and _scan_for_injection(value):
            logger.warning(
                f"工具 {tool_name}: 参数 '{param_name}' 包含可疑模式, "
                f"task_id={task_id}"
            )

    # ── 执行工具 ───────────────────────────────────────────────────
    input_summary = ", ".join(f"{k}={_summarize(v, 80)}" for k, v in params.items())
    logger.debug(f"工具调用: {tool_name}({input_summary})")

    try:
        result = await handler(**params)
    except Exception as e:
        logger.error(f"工具 {tool_name} 执行失败: {e}")
        raise

    # ── 执行后校验 ─────────────────────────────────────────────────
    result_dict = result.model_dump() if hasattr(result, 'model_dump') else result
    if isinstance(result_dict, dict):
        output_text = str(result_dict)
    elif isinstance(result_dict, list):
        output_text = str(result_dict[:3])  # 只检查前 3 项
    else:
        output_text = str(result_dict)

    issue = None
    # 3. 检查输出中是否包含可疑模式
    if _scan_for_injection(output_text):
        issue = f"工具 {tool_name} 输出包含可疑模式"
        logger.warning(issue)

    # 4. 检查关键工具的空结果
    if tool_name == "search_legal_regulations":
        results_list = result_dict.get("results", []) if isinstance(result_dict, dict) else []
        if not results_list:
            logger.info(f"工具 {tool_name}: 未找到相关法规")

    # ── 审计日志（异步，发后即忘） ─────────────────────────────────
    output_summary = _summarize(output_text, 200)
    if user_id and issue:
        _log_tool_call(tool_name, task_id, user_id, input_summary, output_summary, issue)

    return result


def _log_tool_call(
    tool_name: str, task_id: str, user_id: int,
    input_summary: str, output_summary: str, issue: str | None,
) -> None:
    """发后即忘的审计日志记录。"""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_write_tool_audit_log(
            tool_name, task_id, user_id, input_summary, output_summary, issue
        ))
    except RuntimeError:
        pass


async def _write_tool_audit_log(
    tool_name: str, task_id: str, user_id: int,
    input_summary: str, output_summary: str, issue: str | None,
) -> None:
    """将工具调用审计记录写入数据库。"""
    try:
        from app.database import async_session_factory
        from app.models import SecurityAuditLog

        async with async_session_factory() as db:
            log_entry = SecurityAuditLog(
                user_id=user_id,
                event_type="TOOL_GUARD",
                severity="WARNING" if issue else "INFO",
                source="mcp_tool",
                summary=f"{tool_name}: {input_summary}",
                detail={
                    "tool_name": tool_name,
                    "task_id": task_id,
                    "input": input_summary,
                    "output": output_summary,
                    "issue": issue,
                },
            )
            db.add(log_entry)
            await db.commit()
    except Exception as e:
        logger.warning(f"工具审计日志写入失败: {e}")
