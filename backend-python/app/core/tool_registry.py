"""MCP 工具注册中心 —— 基于装饰器的工具注册与发现。

替代 mcp_server.py 中的硬编码导入。通过装饰器注册新工具，mcp_server 遍历注册中心即可。
"""

import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)


class ToolRegistry:
    """MCP 工具注册中心，支持装饰器注册。"""

    def __init__(self):
        self._tools: dict[str, dict[str, Any]] = {}

    def register(self, name: str, description: str = "", schema: Any = None):
        """装饰器：注册一个工具处理函数。

        Args:
            name: 工具名称（必须与 MCP @tool 装饰器名称一致）
            description: 人类可读的工具描述
            schema: 可选的 Pydantic 模型，用于结构化输出
        """
        def decorator(handler: Callable):
            self._tools[name] = {
                "name": name,
                "description": description,
                "handler": handler,
                "schema": schema,
            }
            logger.debug(f"已注册 MCP 工具: {name}")
            return handler
        return decorator

    def get(self, name: str) -> Callable | None:
        """按名称获取工具处理函数。"""
        entry = self._tools.get(name)
        return entry["handler"] if entry else None

    def list_tools(self) -> list[str]:
        """列出所有已注册的工具名称。"""
        return list(self._tools.keys())

    def list_with_descriptions(self) -> list[dict[str, str]]:
        """列出所有工具及其描述。"""
        return [
            {"name": t["name"], "description": t["description"]}
            for t in self._tools.values()
        ]


# 全局单例
tool_registry = ToolRegistry()
register_tool = tool_registry.register
