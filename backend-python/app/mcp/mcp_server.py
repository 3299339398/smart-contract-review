"""MCP Server —— 4 个合同审查工具，通过 Model Context Protocol 暴露。

工具通过 ToolRegistry 发现，而非硬编码导入。
添加新工具时只需用 @register_tool("tool_name") 装饰 handler 即可。
"""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from app.core.tool_registry import tool_registry

SERVER_NAME = "contract-review-tools"
mcp_app = Server(SERVER_NAME)


# ── 遍历注册表注册所有工具 ────────────────────────
# 导入工具模块以触发 @register_tool 装饰器注册
from app.mcp.tools import search_regulations  # noqa: F401
from app.mcp.tools import compare_template    # noqa: F401
from app.mcp.tools import generate_amendment  # noqa: F401
from app.mcp.tools import evaluate_balance    # noqa: F401


def _make_tool_wrapper(handler, _schema=None):
    """创建异步包装器，调用 handler 并返回字典。"""
    async def wrapper(**kwargs):
        result = await handler(**kwargs)
        return result.model_dump() if hasattr(result, 'model_dump') else result
    return wrapper


# 从注册表动态注册工具
for tool_name in tool_registry.list_tools():
    entry = tool_registry._tools[tool_name]
    wrapper = _make_tool_wrapper(entry["handler"], entry.get("schema"))
    wrapper.__name__ = tool_name
    wrapper.__doc__ = entry.get("description", "")
    mcp_app.tool(tool_name)(wrapper)


async def run_mcp_server():
    """通过 stdio 传输运行 MCP 服务器。"""
    async with stdio_server() as (reader, writer):
        await mcp_app.run(reader, writer, mcp_app.create_initialization_options())
