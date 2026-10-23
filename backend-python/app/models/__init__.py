import datetime
from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, Text, Integer, Float, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── 用户表：注册/登录/鉴权，关联 documents、review_tasks、consultation_records ──
class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True)
    email = Column(String(100), nullable=False, unique=True)
    password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="USER")
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    documents = relationship("Document", back_populates="user")
    review_tasks = relationship("ReviewTask", back_populates="user")
    consultation_records = relationship("ConsultationRecord", back_populates="user")


# ── 文档表：上传的合同文件，解析后存 content_text，关联 review_tasks ──
class Document(Base):
    __tablename__ = "documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    original_filename = Column(String(255), nullable=False)
    stored_path = Column(String(500), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    file_type = Column(String(20), nullable=False)
    document_status = Column(String(20), nullable=False, default="UPLOADED")
    content_text = Column(Text)  # MEDIUMTEXT
    clause_count = Column(Integer)
    preview_cache_key = Column(String(255))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="documents")
    review_tasks = relationship("ReviewTask", back_populates="document")


# ── 审查任务表：记录每次审查的状态和进度，1:1 关联 review_results，1:N 关联 risk_items ──
class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    document_id = Column(BigInteger, ForeignKey("documents.id"), nullable=False)
    review_type = Column(String(50), nullable=False, default="FULL")
    status = Column(String(20), nullable=False, default="PENDING")
    total_clauses = Column(Integer, default=0)
    reviewed_clauses = Column(Integer, default=0)
    risk_count_high = Column(Integer, default=0)
    risk_count_medium = Column(Integer, default=0)
    risk_count_low = Column(Integer, default=0)
    python_task_id = Column(String(100))
    result_cache_key = Column(String(255))
    error_message = Column(Text)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="review_tasks")
    document = relationship("Document", back_populates="review_tasks")
    result = relationship("ReviewResult", back_populates="review_task", uselist=False)
    risk_items = relationship("RiskItem", back_populates="review_task")


# ── 审查结果表：与 review_tasks 1:1，存整体评分、摘要、建议、完整报告 JSON ──
class ReviewResult(Base):
    __tablename__ = "review_results"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    review_task_id = Column(BigInteger, ForeignKey("review_tasks.id"), nullable=False, unique=True)
    overall_score = Column(Float(precision=5))
    summary = Column(Text)
    recommendations = Column(JSON)
    full_report_json = Column(JSON)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    review_task = relationship("ReviewTask", back_populates="result")


# ── 风险条目表：每条条款的审查发现，N:1 关联 review_tasks，独立建表支撑统计分析 ──
class RiskItem(Base):
    __tablename__ = "risk_items"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    review_task_id = Column(BigInteger, ForeignKey("review_tasks.id"), nullable=False)
    clause_index = Column(Integer, nullable=False)
    clause_text = Column(Text, nullable=False)
    risk_type = Column(String(100), nullable=False)
    risk_level = Column(String(20), nullable=False)
    risk_description = Column(Text, nullable=False)
    suggested_amendment = Column(Text)
    legal_basis = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    review_task = relationship("ReviewTask", back_populates="risk_items")


# ── 咨询记录表：智能问答历史，存 question/answer/source_clauses(JSON)/token_count ──
class ConsultationRecord(Base):
    __tablename__ = "consultation_records"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    document_id = Column(BigInteger, ForeignKey("documents.id"), nullable=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    source_clauses = Column(JSON)
    token_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="consultation_records")


# ── 安全审计日志表：记录四层安全防线的每次事件(规则拦截/AI分类/工具守卫/人工决策) ──
class SecurityAuditLog(Base):
    __tablename__ = "security_audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    event_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False, default="INFO")
    source = Column(String(50), nullable=False)
    summary = Column(Text, nullable=False)
    detail = Column(JSON)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ── 待审批表：人机协同闸门，高风险操作需用户确认后才继续，24h 自动过期 ──
class PendingApproval(Base):
    __tablename__ = "pending_approvals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    task_id = Column(BigInteger, ForeignKey("review_tasks.id"), nullable=True)
    approval_type = Column(String(50), nullable=False)
    risk_level = Column(String(20), nullable=False)
    risk_reasoning = Column(Text)
    source_text = Column(Text)
    status = Column(String(20), nullable=False, default="PENDING")
    resolved_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
