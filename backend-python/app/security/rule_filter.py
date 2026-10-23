"""第 1 层：基于静态规则的注入检测过滤器。

纯函数，无外部依赖，单模式 O(1) 复杂度。
在攻击到达 LLM 之前检测已知攻击模式。
"""

import re
import unicodedata
from app.security.schemas import FilterResult

# ── Prompt 注入攻击模式 ──────────────────────────────────────────
INJECTION_PATTERNS: list[tuple[str, str]] = [
    # 直接指令覆盖
    (r"(?i)ignore\s+(all\s+)?(previous|prior|above|your)\s+(instructions?|directives?|prompts?)",
     "检测到试图覆盖系统指令的注入模式"),
    (r"(?i)(forget|disregard|override)\s+(your|the)\s+(instructions?|system\s+prompt)",
     "检测到试图覆盖系统指令的注入模式"),
    (r"(?i)you\s+are\s+(now|no\s+longer)\s+(a\s+)?\w+\s+(assistant|bot|AI)",
     "检测到角色转换注入模式"),
    (r"(?i)(from\s+now\s+on|starting\s+now)\s+you\s+(will|must|should|are)",
     "检测到行为重定义注入模式"),
    (r"(?i)pretend\s+(you\s+are|to\s+be)\b",
     "检测到角色扮演注入模式"),

    # 越狱攻击
    (r"(?i)\bDAN\b.*\b(do\s+anything\s+now|mode\s+enabled)",
     "检测到 DAN 越狱攻击模式"),
    (r"(?i)(developer|system|debug)\s*mode\s*(activated|enabled|on)",
     "检测到调试模式越狱"),
    (r"(?i)jailbreak|jail\s*break",
     "检测到越狱尝试关键词"),

    # 提示词提取
    (r"(?i)(output|print|show|reveal|display|tell\s+me)\s+(your|the)\s+(system\s+prompt|instructions?|initial\s+prompt)",
     "检测到试图提取系统提示词"),
    (r"(?i)(what|who)\s+(created|made|built|developed|programmed)\s+you",
     "检测到系统探询模式"),

    # 数据提取
    (r"(?i)(output|dump|list|show)\s+(all|the)\s+(conversations?|messages?|history|users?|documents?)",
     "检测到数据提取尝试"),

    # 编码混淆
    (r"(?i)base64[:\s]*decode|base64[:\s]*encode",
     "检测到 Base64 编码混淆"),
    (r"\\x[0-9a-fA-F]{2}.*\\x[0-9a-fA-F]{2}.*\\x[0-9a-fA-F]{2}",
     "检测到十六进制转义混淆"),

    # 通用越狱前缀
    (r"(?i)^\s*(hi|hello|hey)\s*\.?\s*you\s+will\s+(now\s+)?(act\s+as|pretend|roleplay)",
     "检测到伪装问候的注入模式"),
]

# ── 危险关键词黑名单 ────────────────────────────────────────
DANGEROUS_KEYWORDS: list[tuple[str, str]] = [
    ("<script", "检测到 XSS 攻击载荷"),
    ("__import__", "检测到 Python 代码注入"),
    ("eval(", "检测到代码执行尝试"),
    ("exec(", "检测到代码执行尝试"),
    ("os.system", "检测到系统命令执行尝试"),
    ("subprocess", "检测到系统命令执行尝试"),
    ("<?php", "检测到 PHP 代码注入"),
    ("DROP TABLE", "检测到 SQL 注入尝试"),
    ("UNION SELECT", "检测到 SQL 注入尝试"),
    ("1=1", "检测到 SQL 注入模式"),
    ("${}", "检测到模板注入模式"),
    ("{{", "检测到模板注入模式"),
    ("delete all", "检测到破坏性指令"),
]

# ── 合同结构校验 ──────────────────────────────────────
CONTRACT_KEYWORDS = [
    "甲方", "乙方", "合同", "协议", "条款", "约定",
    "标的", "价款", "履行", "违约", "责任", "争议",
    "甲", "乙", "双方", "协商", "签", "章",
]
MIN_CONTRACT_KEYWORD_DENSITY = 0.03  # 至少 3% 的行包含合同关键词


def _contains_homoglyph_attack(text: str) -> bool:
    """检测混合字母表的同形字攻击（如用西里尔 'а' 伪装拉丁 'a'）。"""
    scripts_found = set()
    for ch in text:
        if ch.isalpha():
            script_name = unicodedata.name(ch, "")
            # 检查是否混合多字母表
            if "CYRILLIC" in script_name:
                scripts_found.add("CYRILLIC")
            elif "LATIN" in script_name:
                scripts_found.add("LATIN")
            elif "GREEK" in script_name:
                scripts_found.add("GREEK")
    # 拉丁 + 西里尔/希腊字母混合为可疑（合同应为中文）
    return "CYRILLIC" in scripts_found or "GREEK" in scripts_found


def filter_text(text: str, source: str = "document") -> FilterResult:
    """运行所有静态规则过滤器。返回包含通过/拦截结论的 FilterResult。"""
    warnings: list[str] = []
    original_text = text

    # ── 1. 清除控制字符（保留换行和制表符） ──
    sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    if sanitized != original_text:
        warnings.append("输入包含控制字符，已自动清除")

    # ── 2. 检查长度限制 ──
    if source == "document" and len(sanitized) > 500_000:
        return FilterResult(
            passed=False,
            blocked_reason=f"文档文本过大（{len(sanitized)} 字符），最大允许 500,000 字符",
            sanitized_text=sanitized[:500_000],
        )
    if source == "query" and len(sanitized) > 5_000:
        return FilterResult(
            passed=False,
            blocked_reason=f"咨询问题过长（{len(sanitized)} 字符），最大允许 5,000 字符",
            sanitized_text=sanitized[:5_000],
        )

    # ── 3. 检查注入模式 ──
    for pattern, reason in INJECTION_PATTERNS:
        if re.search(pattern, sanitized):
            return FilterResult(
                passed=False,
                blocked_reason=reason,
                warnings=warnings,
                sanitized_text=sanitized,
            )

    # ── 4. 检查危险关键词 ──
    for keyword, reason in DANGEROUS_KEYWORDS:
        if keyword.lower() in sanitized.lower():
            return FilterResult(
                passed=False,
                blocked_reason=reason,
                warnings=warnings,
                sanitized_text=sanitized,
            )

    # ── 5. Unicode 同形字检测 ──
    if _contains_homoglyph_attack(sanitized):
        return FilterResult(
            passed=False,
            blocked_reason="检测到可疑的字符混淆（同形字攻击）",
            warnings=warnings,
            sanitized_text=sanitized,
        )

    # ── 6. 合同结构检查（仅文档） ──
    if source == "document":
        lines = [l for l in sanitized.split("\n") if l.strip()]
        if lines:
            contract_line_count = sum(
                1 for line in lines
                if any(kw in line for kw in CONTRACT_KEYWORDS)
            )
            density = contract_line_count / len(lines)
            if density < MIN_CONTRACT_KEYWORD_DENSITY and len(sanitized) > 500:
                warnings.append(
                    f"上传内容可能不是标准合同文本"
                    f"（合同特征关键词密度仅 {density:.1%}，"
                    f"建议阈值 {MIN_CONTRACT_KEYWORD_DENSITY:.0%}）"
                )

    return FilterResult(
        passed=True,
        warnings=warnings,
        sanitized_text=sanitized,
    )
