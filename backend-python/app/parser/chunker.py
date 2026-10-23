"""条款级语义分块器 —— 按中文法律文书编号模式拆分文档。

两级拆分策略：
  1. 主策略：按"第X条/章/节"模式拆分
  2. 次级策略（长条款）：超过 2000 字的单条款按编号子项（(1)、①、分号）拆分
  3. 后备策略：按双换行拆分
"""

import re
import logging

logger = logging.getLogger(__name__)

# 超过此长度的单条款触发次级拆分
LONG_CLAUSE_THRESHOLD = 2000

# 次级拆分的子项模式
SUB_ITEM_PATTERNS = [
    r'\n(?=\(\d+\))',           # (1) (2) (3)
    r'\n(?=（\d+）)',            # （1）（2）（3）
    r'\n(?=\d+[\.、)）]\s)',    # 1. 2.  1) 2)  1、2、
    r'\n(?=[①②③④⑤⑥⑦⑧⑨⑩])',    # ① ② ③
    r'\n(?=（[一二三四五六七八九十]+）)',  # （一）（二）（三）
]


class ClauseLevelChunker:
    """按条款级别对法律文档做语义分块。"""

    CLAUSE_PATTERNS = [
        re.compile(r'第[一二三四五六七八九十百千\d]+条'),
        re.compile(r'第[一二三四五六七八九十百千\d]+章'),
        re.compile(r'第[一二三四五六七八九十百千\d]+节'),
        re.compile(r'^\d+[\.、）)]\s*'),
    ]

    def split_clauses(self, text: str) -> list[str]:
        """将文档文本拆分为条款列表（含长条款次级拆分）。"""
        # 主策略：正则拆分
        clauses = self._split_by_patterns(text)

        # 拆不出有效条款时用后备方案
        if len(clauses) <= 1:
            clauses = self._split_by_newlines(text)

        # 次级拆分：超过阈值的条款进一步拆分
        result = []
        for clause in clauses:
            cleaned = clause.strip()
            if len(cleaned) > LONG_CLAUSE_THRESHOLD:
                sub_clauses = self._split_long_clause(cleaned)
                logger.info(f"长条款（{len(cleaned)}字）拆分为 {len(sub_clauses)} 个子条款")
                result.extend(sub_clauses)
            elif len(cleaned) > 20:
                result.append(cleaned)

        logger.info(f"文档分块完成，共 {len(result)} 个条款")
        return result

    def _split_by_patterns(self, text: str) -> list[str]:
        """按预设的条款编号模式拆分文本。"""
        combined = '|'.join(p.pattern for p in self.CLAUSE_PATTERNS)
        parts = re.split(f'({combined})', text)

        clauses = []
        current = ""
        for part in parts:
            if part and any(p.match(part) for p in self.CLAUSE_PATTERNS):
                if current.strip():
                    clauses.append(current.strip())
                current = part
            else:
                current += part

        if current.strip():
            clauses.append(current.strip())

        return clauses

    def _split_by_newlines(self, text: str) -> list[str]:
        """后备方案：按双换行（段落）拆分。"""
        parts = re.split(r'\n\s*\n', text)
        return [p.strip() for p in parts if len(p.strip()) > 20]

    def _split_long_clause(self, text: str) -> list[str]:
        """对超长条款做次级拆分：先尝试编号子项模式，失败则按分号断句。"""
        # 1. 尝试按编号子项拆分
        for pattern in SUB_ITEM_PATTERNS:
            parts = re.split(pattern, text)
            parts = [p.strip() for p in parts if len(p.strip()) > 20]
            if len(parts) >= 2:
                return parts

        # 2. 尝试按分号 + 换行拆分（中文合同常用格式）
        if '\n' in text:
            semicolon_parts = re.split(r'；\s*\n', text)
        else:
            semicolon_parts = re.split(r'；(?=\s*[甲乙丙丁戊己庚辛壬癸\d])', text)

        parts = [p.strip() + '；' for p in semicolon_parts if len(p.strip()) > 30]
        if len(parts) >= 2:
            return parts

        # 3. 降级：只取前 2000 字符作为一段，剩余部分单独成段
        if len(text) > LONG_CLAUSE_THRESHOLD:
            return [text[:LONG_CLAUSE_THRESHOLD].strip(), text[LONG_CLAUSE_THRESHOLD:].strip()]

        return [text]
