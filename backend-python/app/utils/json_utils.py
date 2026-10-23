"""从 LLM 响应中提取有效 JSON 的工具函数。

LLM 经常将 JSON 包裹在 Markdown 代码块中，格式多样：
  ```json\n{...}\n```
  ```\n{...}\n```
  { ... }  （无代码块标记，但包含多余空白字符）

本模块处理上述所有常见变体，以及 JSON 对象前后出现额外文本的情况。
"""

import re
import json as json_lib
import logging

logger = logging.getLogger(__name__)


def extract_json(text: str) -> str:
    """从 LLM 输出中提取纯净 JSON 字符串，去除 Markdown 代码块标记。

    处理场景：
      - 首尾空白字符
      - 带可选语言标记的 Markdown 代码块（```json、``` 等）
      - 带前导空格的代码块标记
      - JSON 对象前后的多余文本
    """
    text = text.strip()

    # 去除 Markdown 代码块标记：可选空白、```、可选语言标记、换行
    text = re.sub(r'^\s*```(?:json)?\s*\n?', '', text, count=1)
    # 去除 next line 上独立存在的语言标记
    text = re.sub(r'^\s*json\s*\n', '', text, count=1)
    # 去除尾部代码块标记：可选换行、可选空白、```
    text = re.sub(r'\n?\s*```\s*$', '', text, count=1)

    # 如果结果已是合法 JSON，直接返回
    text = text.strip()
    if text.startswith('{') and text.endswith('}'):
        return text

    # 否则，查找文本中第一个 JSON 对象
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        return match.group()

    # 放弃，返回原始文本 — 调用方处理解析失败
    return text


def parse_json(text: str):
    """从 LLM 输出中提取并解析 JSON，返回解析后的字典或 None。"""
    try:
        cleaned = extract_json(text)
        return json_lib.loads(cleaned)
    except (json_lib.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"Failed to parse JSON from LLM output: {e}")
        return None
