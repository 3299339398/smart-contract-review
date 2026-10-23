"""合同文档文本处理工具。"""

import re


def clean_document_text(text: str) -> str:
    """上传时清洗文档文本：去掉控制字符、统一换行符、合并多余空白。

    与 rule_filter.filter_text() 不同，这里不做安全拦截——只清洗格式。
    安全审查在后续 SecurityPipeline 中独立进行。
    """
    # 清除 ASCII 控制字符（保留 \t \n）
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    # 统一换行符
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 合并连续空行（>2 个连续换行 → 压缩为 2 个）
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 合并行内多余空格
    text = re.sub(r'[ \t]{2,}', ' ', text)
    # 去除首尾空白
    return text.strip()


def normalize_text(text: str) -> str:
    """规范化文本：合并多余空白、统一换行符、处理全角空格。"""
    text = " ".join(text.split())
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("　", " ")
    return text


def extract_clause_number(text: str) -> int | None:
    """从条款文本中提取条款编号（如 '第四条' → 4, '第15条' → 15）。"""

    cn_map = {
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    }
    match = re.search(r'第([一二三四五六七八九十\d]+)条', text)
    if match:
        num_str = match.group(1)
        if num_str.isdigit():
            return int(num_str)
        if num_str in cn_map:
            return cn_map[num_str]
    return None


def count_chinese_chars(text: str) -> int:
    """统计文本中的中文字符数量。"""
    return sum(1 for c in text if '一' <= c <= '鿿')


def truncate_head_tail(text: str, max_chars: int, head_ratio: float = 0.7) -> str:
    """截断文本：取头部 + 尾部，保留中间省略标记。

    与纯头部截断不同，此策略保留尾部信息（法律条款的违约责任、救济措施常在尾部）。
    """
    if len(text) <= max_chars:
        return text

    omit_marker = "\n\n…[中间内容省略]…\n\n"
    marker_len = len(omit_marker)
    available = max_chars - marker_len
    if available <= 0:
        return text[:max_chars - 3] + "…"

    head_len = int(available * head_ratio)
    tail_len = available - head_len

    head = text[:head_len]
    tail = text[-tail_len:] if tail_len > 0 else ""
    return head + omit_marker + tail


def truncate_text(text: str, max_chars: int) -> str:
    """截断文本到指定长度，使用头+尾策略保留关键信息。"""
    return truncate_head_tail(text, max_chars)
