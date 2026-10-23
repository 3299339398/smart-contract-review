"""安全模块 Pydantic 模型 —— 安全审查结果的数据结构。"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RiskClass(str, Enum):
    SAFE = "SAFE"
    SUSPICIOUS = "SUSPICIOUS"
    MALICIOUS = "MALICIOUS"


class ApprovalType(str, Enum):
    SECURITY_REVIEW = "SECURITY_REVIEW"
    HIGH_RISK_CONFIRM = "HIGH_RISK_CONFIRM"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class SecurityEventType(str, Enum):
    RULE_BLOCKED = "RULE_BLOCKED"
    AI_CLASSIFY = "AI_CLASSIFY"
    TOOL_GUARD = "TOOL_GUARD"
    HUMAN_APPROVE = "HUMAN_APPROVE"
    HUMAN_REJECT = "HUMAN_REJECT"


class SecuritySeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class FilterResult:
    passed: bool
    blocked_reason: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    sanitized_text: str = ""


@dataclass
class ClassifyResult:
    risk_class: RiskClass
    reasoning: str = ""
    risk_score: float = 0.0


@dataclass
class GuardResult:
    passed: bool
    tool_name: str
    issue: Optional[str] = None
    input_summary: str = ""
    output_summary: str = ""


@dataclass
class SecurityVerdict:
    passed: bool
    risk_class: RiskClass
    blocked: bool
    requires_approval: bool
    filter_result: Optional[FilterResult] = None
    classify_result: Optional[ClassifyResult] = None
    approval_id: Optional[int] = None
