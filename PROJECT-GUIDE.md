# 智能合同审查平台 — 项目代码导航指南

> 面试复习专用：覆盖全部 87 个源文件，含每个文件的职责、对外暴露的方法、调用关系。

---

## 一、项目总览

```
smart-contract-review/
├── docker-compose.yml          # Docker 编排：MySQL + Redis + ChromaDB + FastAPI + Nginx
├── .env / .env.example         # 环境变量（API Key、密码等）
├── vm-start-services.sh        # 虚拟机独立启动中间件脚本
├── backend-python/             # FastAPI 后端（Python 3.12+）
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py             # 应用入口（FastAPI 实例、lifespan、CORS）
│       ├── config.py           # 全局配置（Pydantic Settings，读 .env）
│       ├── database.py         # MySQL 异步引擎 + session 工厂
│       ├── models/__init__.py  # 8 张 SQLAlchemy 表定义
│       ├── api/                # 4 个路由模块
│       ├── services/           # 5 个业务逻辑服务
│       ├── agent/              # LangGraph 审查管线（状态 + 图 + 7 节点 + 3 条件边）
│       ├── rag/                # RAG 检索管线（7 步：改写→路由→混合→精排→组装→生成→校验）
│       ├── mcp/                # MCP 工具体系（注册中心 + 4 个审查工具 + MCP Server）
│       ├── security/           # 四层安全防线（规则→AI→守卫→人工）
│       ├── cache/              # L1 内存 + L2 Redis 双层缓存
│       ├── embeddings/         # ChromaDB 向量存储 + Embedding 服务
│       ├── core/               # Provider 抽象层（LLM 工厂 + Embedding 工厂 + 工具注册中心）
│       ├── parser/             # 文档解析（PDF/DOCX/TXT）+ 条款分块
│       ├── llm/                # LLM 客户端兼容层（委托给 Provider）
│       ├── utils/              # JWT、Redis、bcrypt、JSON 解析、日志
│       ├── middleware/          # JWT 认证中间件
│       └── schemas/            # Pydantic 请求/响应模型
└── frontend/                   # React 19 + TypeScript + Vite
    └── src/
        ├── main.tsx / App.tsx   # 应用入口 + 路由
        ├── api/client.ts        # Axios 客户端（自动 token 刷新）
        ├── store/authStore.ts   # Zustand 认证状态
        ├── hooks/               # 自定义 Hook
        ├── pages/               # 5 个页面组件
        ├── components/          # 3 个共享组件
        └── types/               # 4 个 TypeScript 类型文件
```

---

## 二、后端文件详解（逐文件）

### 2.1 应用入口层（2 个文件）

| 文件 | 类/函数 | 做了什么 | 调用了谁 |
|------|---------|---------|---------|
| `app/main.py` | `app = FastAPI(...)` | 创建 FastAPI 实例、配置 CORS、注册路由 `/api/v1`、定义 `/` 和 `/health` 端点 | `api.router.api_router`, `config.settings`, `database.init_db`, `core.llm_provider.LLMProviderFactory` |
| | `lifespan()` | 启动时依次连接 ChromaDB → MySQL 建表 → 初始化 LLM/Embedding Provider；关闭时释放数据库连接池 | `chromadb.HttpClient`, `database.init_db`, `core` |

| `app/config.py` | `class Settings(BaseSettings)` | 从 `.env` 和环境变量加载所有配置（ChromaDB/LLM/Embedding/RAG/MySQL/Redis/JWT/Upload），含 RAG 管线全部开关和阈值 | 无（被各模块通过 `app.config.settings` 读取） |

---

### 2.2 数据库层（2 个文件）

| 文件 | 类/函数 | 做了什么 | 调用了谁 |
|------|---------|---------|---------|
| `app/database.py` | `DATABASE_URL` | 拼接 `mysql+aiomysql://` 连接串 | `config.settings` |
| | `engine` / `async_session_factory` | 创建异步引擎（pool_size=10）和 session 工厂 | SQLAlchemy |
| | `get_db()` | FastAPI 依赖注入：每次请求 yield 一个 AsyncSession | `async_session_factory` |
| | `init_db()` | 启动时自动建表：`Base.metadata.create_all` | `models.Base` |

| `app/models/__init__.py` | `class User(Base)` | users 表：id, username, email, password, role, enabled | SQLAlchemy ORM |
| | `class Document(Base)` | documents 表：user_id FK, filename, stored_path, file_size, content_text, clause_count, document_status | SQLAlchemy ORM |
| | `class ReviewTask(Base)` | review_tasks 表：user_id FK, document_id FK, review_type, status, risk_count_high/medium/low, python_task_id | SQLAlchemy ORM |
| | `class ReviewResult(Base)` | review_results 表：review_task_id FK(unique), overall_score, summary, recommendations(JSON), full_report_json(JSON) | SQLAlchemy ORM |
| | `class RiskItem(Base)` | risk_items 表：review_task_id FK, clause_index, clause_text, risk_type, risk_level, risk_description, suggested_amendment, legal_basis | SQLAlchemy ORM |
| | `class ConsultationRecord(Base)` | consultation_records 表：user_id FK, document_id FK, question, answer, source_clauses(JSON), token_count | SQLAlchemy ORM |
| | `class SecurityAuditLog(Base)` | security_audit_logs 表：user_id FK, event_type, severity, source, summary, detail(JSON) | SQLAlchemy ORM |
| | `class PendingApproval(Base)` | pending_approvals 表：user_id FK, task_id FK, approval_type, risk_level, risk_reasoning, source_text, status | SQLAlchemy ORM |

**表关系：**
```
users ──< documents ──< review_tasks ──< risk_items
                                │
                                └── review_results (1:1)
users ──< consultation_records
users ──< security_audit_logs
users ──< pending_approvals
```

**数据库设计要点（面试用）：**

> **整体思路**：8 张表围绕一条主线「用户上传合同 → 审查任务 → 风险发现 → 结果输出」，外加两张独立表支撑安全审计和人工审批。MySQL + SQLAlchemy 异步引擎，连接池 10+20，全链路 async。

| 设计决策 | 为什么这样做 | 面试时怎么说 |
|---------|------------|------------|
| `risk_items` 独立建表，而非放 `review_results` 的 JSON 字段 | JSON 字段放 WHERE 条件里无法走 B-tree 索引，跨合同统计分析（如"近三个月 LIABILITY_UNLIMITED 类型风险的出现频率"）需要全表扫描再解析 | "risk_type 和 risk_level 加联合索引，查询效率远高于 JSON 字段扫描。独立行也方便做风险趋势看板。" |
| `review_results` 与 `review_tasks` 1:1 拆分（unique FK） | 职责分离：review_tasks 管流程状态（PENDING→PROCESSING→COMPLETED），review_results 管业务产出（评分/摘要/报告）。合并会导致大量 NULL 列——审查未完成时 overall_score 和 summary 都是空的 | "拆开更干净，也方便后续扩展审查结果的版本管理。" |
| `recommendations` 和 `full_report_json` 用 JSON 列 | 这两个字段**只写不读（仅前端展示）**，永远不会出现在 WHERE 条件里，不需要索引 | "真正需要查询的字段如 risk_type、risk_level 都在 risk_items 里用普通 VARCHAR 列，不会受 JSON 列性能影响。" |
| `result_cache_key` 和 `preview_cache_key` 冗余字段 | 存放 sha256 哈希，前端重复请求同一审查结果时先查缓存键命中直接走 Redis，不查数据库也不重新跑 Agent 管线 | "用冗余换一次 LLM 调用的费用，这个 trade-off 很值。" |
| `pending_approvals` 独立于业务表 | 第四层安全防线（人机协同闸门）的持久化。HIGH 级别风险的修改建议先写 PENDING，用户确认后才流转为 APPROVED | "高风险操作有完整的审批追溯链，24 小时自动过期防止积压。" |
| `security_audit_logs` 的 `detail` 用 JSON | 不同安全事件结构差异大——规则拦截只记录匹配模式，AI 分类要记录置信度加推理过程 | "JSON 列比 EAV（实体-属性-值）模式简洁得多，且审计日志只追加不修改，不存在更新异常。" |
| 为什么用 MySQL 而不用 PostgreSQL | Docker Compose 部署目标用户可能是中小企业法务团队，MySQL 运维门槛更低。项目用到的向量检索走 ChromaDB，不依赖关系型数据库的专有特性 | "没有用到 PG 的数组类型、全文检索等专有特性，MySQL 完全够用，且受众更广。" |

**如果面试官追问：**

- **"为什么不用 MongoDB？"** → 合同审查数据高度结构化（用户→文档→任务→风险条目的层级关系），关系型数据库天然适合。MongoDB 的事务支持和 JOIN 能力弱于 MySQL，不适合需要级联删除（删文档→删向量→删审查记录）的场景。
- **"高并发下连接池够用吗？"** → pool_size=10 + max_overflow=20，峰值 30 连接。合同审查不是高并发场景（用户上传文档后异步处理），瓶颈在 LLM API 调用延迟而非数据库连接数。
- **"索引怎么建的？"** → 外键列（user_id, document_id, review_task_id）默认建索引。核心查询路径——按用户查文档、按任务查风险条目——都走外键覆盖。如需扩展看板统计，会在 risk_items 的 risk_type + risk_level 上加联合索引。

---

### 2.3 API 路由层（6 个文件）

| 文件 | 路由前缀 | 端点 | 做了什么 | 调用了谁 |
|------|---------|------|---------|---------|
| `app/api/router.py` | `/api/v1` | — | 汇总所有子路由，挂载 auth/document/review/consultation/security 五组路由 | 各子路由模块 |
| `app/api/auth_router.py` | `/api/v1/auth` | POST `/register`, `/login`, `/refresh`, `/logout` | 注册、登录（发 access+refresh token）、刷新 token、登出（token 黑名单） | `AuthService.register/login/refresh/logout` |
| `app/api/document_router.py` | `/api/v1/documents` | POST `/upload`, GET `""`, GET `/{id}`, DELETE `/{id}` | 上传文档（自动解析+建索引）、列表查询（分页+状态过滤）、详情查看、删除（同时清向量库和文件） | `DocumentService.upload/list_documents/get_document/delete_document` |
| `app/api/review_router.py` | `/api/v1/reviews` | POST `/reviews`, GET `/reviews`, GET `/reviews/{id}`, DELETE `/reviews/{id}`, GET `/reviews/{id}/result`, GET `/reviews/{id}/stream` | 创建审查任务→后台 agent 执行、任务列表、任务详情、任务删除、结果查询（含缓存）、SSE 事件流 | `ReviewService.create_review/get_task/list_tasks/delete_task/get_result`, `sse_service.create_sse_stream` |
| | 旧路由 `/api/v1/review` | POST `/start`, GET `/status/{id}`, POST `/parse` | 向后兼容的旧 API（不依赖数据库，直接文本审查） | `agent.graph.build_review_graph`, `agent.state.create_initial_state`, `parser.DocumentParserFactory` |
| `app/api/consultation_router.py` | `/api/v1/consultations` | POST `/consultations`, GET `/consultations` | 智能问答（走安全管线→RAG 7 步→保存记录）、历史记录查询 | `ConsultationService.ask/get_history`, `rate_limit_service.rate_limit` |
| | 旧路由 `/api/v1/consult` | POST `/ask` | 向后兼容的旧 Q&A 端点 | `rag.consultation_chain.answer_question` |
| `app/api/security_router.py` | `/api/v1/security` | GET `/approvals`, GET `/approvals/{id}`, POST `/{id}/approve`, POST `/{id}/reject`, GET `/audit-logs` | 审批列表、审批详情、批准/拒绝审批、安全审计日志查询 | `security.human_gate.list_pending_approvals/get_approval/approve_approval/reject_approval`, `models.SecurityAuditLog` |

---

### 2.4 业务服务层（5 个文件）

| 文件 | 类 | 公开方法 | 做了什么 | 核心调用 |
|------|-----|---------|---------|---------|
| `app/services/auth_service.py` | `AuthService` | `register()` | 检查 email/username 唯一性 → bcrypt 哈希密码 → 写入 users 表 | `utils.security.hash_password`, `models.User` |
| | | `login()` | 验证密码 → 签发 access+refresh token → 存入 Redis | `utils.security.verify_password`, `utils.jwt_utils.create_access_token/create_refresh_token`, `utils.redis_utils.get_redis` |
| | | `refresh()` | 验证 refresh token → 签发新 token 对（token rotation） | `utils.jwt_utils.decode_token`, `models.User` |
| | | `logout()` | 提取 access token hash → 写入 Redis 黑名单 → 删除 Redis 中的 token | `utils.redis_utils.get_redis`, `utils.jwt_utils.get_token_hash` |
| `app/services/document_service.py` | `DocumentService` | `upload()` | 6 层校验 → 存文件 → 解析文本 → 拆分条款 → 写 MySQL → 建向量索引（ChromaDB）+ BM25 索引 | `services.file_validator.validate`, `parser.DocumentParserFactory`, `parser.ClauseLevelChunker`, `embeddings.vector_store.add_clauses`, `rag.hybrid_retriever.index_clauses` |
| | | `list_documents()` | 分页查询 documents 表，支持 status 过滤 | `models.Document` |
| | | `get_document()` | 按 id + user_id 查询，返回 content_text 前 2000 字预览 | `models.Document` |
| | | `delete_document()` | 删磁盘文件 → 删 ChromaDB 向量 → 删 MySQL 记录 | `embeddings.vector_store.delete_document`, `models.Document` |
| `app/services/review_service.py` | `ReviewService` | `create_review()` | 验证文档归属 → 创建 ReviewTask(status=PENDING) → `asyncio.create_task(_run_review)` 后台执行 | `models.Document`, `models.ReviewTask` |
| | | `_run_review()` | **核心审查执行流程**：安全管线检测 → 防注入拦截/审批 → LangGraph agent(7节点) 流式执行 → SSE 实时推送事件 → 保存 ReviewResult + RiskItems | `security.SecurityPipeline.check_document`, `agent.state.create_initial_state`, `agent.graph.build_review_graph`, `sse_service.send_event` |
| | | `get_result()` | 查缓存 → 查 review_results 表 → 查 risk_items 表 → 组装返回 → 写缓存 | `cache.cache_manager`, `models.ReviewResult`, `models.RiskItem` |
| | | `get_task/list_tasks/delete_task()` | 单条查询/分页列表/级联删除（risk_items → review_results → review_tasks） | `models.ReviewTask`, `models.Document` |
| `app/services/consultation_service.py` | `ConsultationService` | `ask()` | 安全管线 → 获取文档条款 → RAG 7 步检索 → 保存 ConsultationRecord → 返回答案 | `security.SecurityPipeline.check_query`, `rag.consultation_chain.answer_question`, `models.ConsultationRecord` |
| | | `get_history()` | 分页查询咨询记录 | `models.ConsultationRecord` |
| `app/services/sse_service.py` | — | `subscribe(task_id)` | 创建 asyncio.Queue 并注册为 SSE 订阅者 | 无（内存队列） |
| | | `send_event(task_id, type, **data)` | 向指定 task 的所有订阅者队列推送 SSE 事件 | 无 |
| | | `complete_task(task_id)` | 发送 None 信号关闭流 | 无 |
| | | `create_sse_stream(task_id)` | 创建 `StreamingResponse`（text/event-stream），15s heartbeat | FastAPI StreamingResponse |

---

### 2.5 LangGraph 审查管线（9 个文件）

#### 状态定义

| 文件 | 类/函数 | 做了什么 |
|------|---------|---------|
| `app/agent/state.py` | `class AgentState(TypedDict)` | 全局共享状态类型：document_text, review_type, task_id, parsed_text, clauses[], current_clause_index, total_clauses, all_risks[], overall_score, summary, recommendations[] |
| | `class Clause(TypedDict)` | 每条条款的完整类型：index, text, risk_type, risk_level, risk_description, suggested_amendment, legal_basis, compliance_issues, 各节点 reasoning, MCP 检索字段 |
| | `class RiskItem(TypedDict)` | 结构化风险条目：clause_index, clause_text, risk_type, risk_level, risk_description, suggested_amendment, legal_basis |
| | `create_initial_state()` | 工厂函数，用 API 入参填充初始状态 |

#### 图定义与条件边

| 文件 | 类/函数 | 做了什么 | 调用了谁 |
|------|---------|---------|---------|
| `app/agent/graph.py` | `build_review_graph()` | 构建 StateGraph：8 个节点(parse→extract→next_clause→risk_type_identify→severity_check→compliance_check→amendment_generate→aggregate_report)，3 条条件边(has_risk, check_review_type, more_clauses)，入口 parse_document，出口 aggregate_report→END | 7 个 node 模块, `edges.conditions` |
| | `build_compiled_graph()` | 编译图 + 设置 recursion_limit=200 | 无 |
| `app/agent/edges/conditions.py` | `has_risk(state)` | 条件：当前条款 risk_type != NONE → severity_check，否则跳过 | 无（纯逻辑） |
| | `more_clauses(state)` | 条件：current_clause_index < total_clauses - 1 → 循环 next_clause，否则 → aggregate | 无 |
| | `check_review_type(state)` | 条件：RISK_ONLY 模式 → 跳过合规检查 → amendment_generate；FULL → compliance_check | 无 |

#### 7 个 Agent 节点

| 文件 | 节点名 | LLM 调用 | MCP 工具 | 做了什么 |
|------|--------|---------|---------|---------|
| `agent/nodes/parse_node.py` | `parse_document` | 无 | 无 | 最后一道安全网：统一换行符 `\r\n` → `\n`（主清洗在上传时 clean_document_text + 安全管线 filter_text 已完成） |
| `agent/nodes/extract_clauses_node.py` | `extract_clauses` | 无 | 无 | 委托 `ClauseLevelChunker.split_clauses()` 做两级拆分（主策略 + 长条款次级拆分）→ 过滤过短碎片 → 产出 `clauses[]` + `total_clauses` |
| `agent/nodes/risk_type_identify_node.py` | `risk_type_identify` | DeepSeek + CoT 4步 | 无 | 对当前条款用 LLM 从 13 种预定义风险类型中判断类型(NONE=无风险)，写入 `clause.risk_type` |
| `agent/nodes/severity_check_node.py` | `severity_check` | DeepSeek + CoT 4步 | compare_with_template | 先调 MCP 模板对比 → 再让 LLM 综合判定 HIGH/MEDIUM/LOW 风险等级，写入 `clause.risk_level` + `risk_description`，追加到 `all_risks[]` |
| `agent/nodes/compliance_check_node.py` | `compliance_check` | DeepSeek + CoT 4步 | search_legal_regulations | 先 MCP 检索法规 → LLM 综合写合规分析，写入 `clause.legal_basis` + `compliance_issues` |
| `agent/nodes/amendment_generate_node.py` | `amendment_generate` | DeepSeek + CoT 4步（润色用） | generate_amendment | 先 MCP 生成修改方案 → LLM 润色。三层降级：MCP LLM→MCP 模板→LLM 直接生成，写入 `clause.suggested_amendment` |
| `agent/nodes/aggregate_report_node.py` | `aggregate_report` | DeepSeek + CoT 5步 | 无 | 统计所有风险 → LLM 生成综合评分(0-100)、摘要、建议。LLM 失败用启发式兜底 |

**节点间数据流：**
```
parse ──parsed_text──→ extract ──clauses[]──→ next_clause ──current_clause_index──→
risk_type_identify ──clause.risk_type──→ severity_check ──clause.risk_level──→
compliance_check ──clause.legal_basis──→ amendment_generate ──clause.suggested_amendment──→
aggregate_report ──overall_score, summary, recommendations──→ END
```

所有节点共享同一个 `AgentState` TypedDict，每个节点只读写自己关心的字段。

---

### 2.6 RAG 检索管线（9 个文件）

| 步骤 | 文件 | 类/函数 | 做了什么 | 调用了谁 |
|------|------|---------|---------|---------|
| **总调度** | `app/rag/consultation_chain.py` | `answer_question()` | **7 步管线编排**：按顺序调用 query_rewriter → question_router → hybrid_retriever → secondary_retriever → reranker → context_assembler → llm_client → citation_verifier。含缓存读写 | 以下全部子模块 |
| Step 1 | `app/rag/query_rewriter.py` | `QueryRewriter.rewrite()` | 法律术语扩展：把"违约金"扩展为"违约金 违约责任 损害赔偿"，通过内置 14 组同义词映射 | jieba 分词 |
| | | `rewrite_with_llm()` | LLM 一 shot 生成 1-3 个改写查询，带缓存 | `llm.client.llm_client` |
| Step 2 | `app/rag/question_router.py` | `QuestionRouter.route()` | 正则分类为 5 种类型(EXACT_LOOKUP/SEMANTIC/KEYWORD/CONCEPTUAL/COMPARISON)，返回各通道权重 | 正则（零成本） |
| | | `route_with_llm()` | 正则兜不住时用 LLM 分类，带缓存 | `llm.client.llm_client` |
| Step 3 | `app/rag/hybrid_retriever.py` | `HybridRetriever.search()` | BM25+向量并行召回 → RRF 融合(RRF k=60) → 去重+校准 → 返回 top_k，支持路由权重覆盖 | `rag.bm25_retriever`, `embeddings.vector_store` |
| | `app/rag/bm25_retriever.py` | `BM25Retriever.search()` | jieba 分词后 BM25 评分，返回归一化分数 | jieba, rank_bm25 |
| Step 7b | `app/rag/secondary_retriever.py` | `SecondaryRetriever.should_retry()` | 判断 top-k 最大分是否低于阈值 | 无 |
| | | `retrieve()` | 低置信度时触发：查询扩展(多 query 加权融合)/跨文档检索/MMR 多样性检索 | `rag.hybrid_retriever`, `embeddings.vector_store` |
| Step 4 | `app/rag/reranker.py` | `Reranker.rerank()` | BGE-reranker-base CrossEncoder 对候选池逐对评分，返回精排结果 | `sentence_transformers.CrossEncoder` |
| Step 5 | `app/rag/context_assembler.py` | `ContextAssembler.assemble()` | Token 预算管理：按 rerank_score 排序 → 截断过长条款 → 格式化元数据头 → 预算耗尽停止打包 | 无 |
| Step 6 | | `answer_question()` 内部 | LLM 生成答案（带条款引用） | `llm.client.llm_client` |
| Step 7 | `app/rag/citation_verifier.py` | `CitationVerifier.verify()` | 提取 LLM 回答中的"第X条"引用 → 与检索结果交叉比对 → 幻觉条款追加警告标记 | 正则 + 中文数字转换 |

**RAG 数据流：**
```
用户问题 → Step1 改写(1-N变体) → Step2 路由(通道权重) → Step3 BM25+向量RRF融合
→ Step7b 低置信度二次检索 → Step4 BGE精排 → Step5 Context打包
→ Step6 LLM生成 → Step7 引用校验 → 返回(answer, sources, meta)
```

---

### 2.7 MCP 工具体系（7 个文件）

| 文件 | 类/函数 | 做了什么 | 调用了谁 |
|------|---------|---------|---------|
| `app/core/tool_registry.py` | `ToolRegistry.register()` | 装饰器 `@register_tool(name)`：将 handler 注册到全局字典 `_tools`，支持动态发现 | 无 |
| | `tool_registry.list_tools()` | 返回所有已注册工具名列表 | 无 |
| `app/mcp/mcp_server.py` | `run_mcp_server()` | 启动 MCP stdio server：遍历 ToolRegistry 动态注册所有工具 | mcp SDK, `core.tool_registry` |
| `app/mcp/tools/search_regulations.py` | `handler(query, risk_type, jurisdiction)` | 法规语义检索：加载内置法规库(正则→关键词→embedding 语义排序)，含 fallback 逻辑 | `embeddings.embedding_service`, `@register_tool` |
| `app/mcp/tools/compare_template.py` | `handler(clause_text, template_type, clause_category)` | 条款与 4 类标准模板(EMPLOYMENT/NDA/LEASE/SERVICE)做 embedding 语义对比，低分项送 LLM 深度分析 | `embeddings.embedding_service`, `llm.client.llm_client`, `@register_tool` |
| `app/mcp/tools/generate_amendment.py` | `handler(clause_text, risk_type, risk_description, reference_regulations)` | 修改建议生成：LLM 首选 → 5 种风险类型内置模板 fallback，三级降级链 | `llm.client.llm_client`, `@register_tool` |
| `app/mcp/tools/evaluate_balance.py` | `handler(clauses, contract_type, favored_party)` | 合同公平性评估：9 种单方条款模式扫描→启发式打分→高风险触发 LLM 深度分析 | `llm.client.llm_client`, `@register_tool` |

---

### 2.8 安全防线（5 个文件）

| 层级 | 文件 | 类/函数 | 做了什么 | 速度 |
|------|------|---------|---------|------|
| **管线入口** | `app/security/__init__.py` | `SecurityPipeline.check_document()` | L1规则→L2 AI→决策分发：MALICIOUS拦截/SUSPICIOUS创建审批/SAFE放行。写审计日志 | — |
| | | `check_query()` | 同上但针对咨询问题，SUSPICIOUS 只记录不拦截 | — |
| **L1 规则** | `app/security/rule_filter.py` | `filter_text(text, source)` | 6 项检查：控制字符清理→长度限制(doc 500K/query 5K)→12 组注入正则→13 组危险关键词→同形字攻击→合同特征密度 | O(1) |
| **L2 AI** | `app/security/risk_classifier.py` | `classify_text(text)` | 取头尾 2500 字→LLM CoT 分类为 SAFE/SUSPICIOUS/MALICIOUS；5 秒超时降级 SAFE | LLM <5s |
| **L3 守卫** | `app/security/tool_guard.py` | `guard_tool_call(tool_name, handler, params)` | 工具调用包装器：参数长度检查→注入扫描→执行→输出异常扫描→异步审计日志 | 轻量 |
| **L4 人工** | `app/security/human_gate.py` | `create_approval()` | 创建 PendingApproval + SSE 告警 | 写 DB |
| | | `approve_approval()` / `reject_approval()` | 批准/拒绝审批，写审计日志 | 写 DB |
| | | `list_pending_approvals()` | 列出待审批，自动过期 24h | 查 DB |
| **安全模型** | `app/security/schemas.py` | `FilterResult, ClassifyResult, GuardResult, SecurityVerdict` | 4 种安全判定结果的数据类，含 risk_class(SAFE/SUSPICIOUS/MALICIOUS), approval type/status 枚举 | — |

**防线调用链：**
```
REST API 请求中的文本
    ↓
SecurityPipeline.check_document() 或 .check_query()
    ├── L1: rule_filter.filter_text()     → 拦截 MALICIOUS 直接返回
    ├── L2: risk_classifier.classify_text() → 记录审计日志
    └── 决策:
         MALICIOUS  → blocked=True  (拒绝)
         SUSPICIOUS → requires_approval=True (L4: human_gate.create_approval)
         SAFE       → passed=True (放行)
    ↓
Agent 节点内: guard_tool_call() (L3) 包装每个 MCP 工具调用
```

---

### 2.9 缓存系统（3 个文件）

| 层 | 文件 | 类 | 特点 |
|----|------|-----|------|
| **管理器** | `app/cache/__init__.py` | `CacheManager` | 统一接口 `get(key)→set(key,val,ttl)→delete(key)`，自动 L2→L1 提升 |
| **L1 内存** | `app/cache/memory_cache.py` | `MemoryCache` | OrderedDict LRU，max_size=512，线程安全（threading.Lock），微秒级 |
| **L2 Redis** | `app/cache/redis_cache.py` | `RedisCache` | Key 前缀 `scr:cache:`，TTL 支持，Redis 不可用时静默降级 |

**缓存使用场景：**
- `llm_cache_ttl=3600`：LLM `chat()` 和 `chat_with_cot()` 在 `core/llm_provider.py` 的 `DeepSeekProvider` 里写缓存
- `rag_cache_ttl=600`：RAG `answer_question()` 结果全文缓存（须完全匹配）
- `review_cache_ttl=3600`：`ReviewService.get_result()` 对审查结果写缓存

---

### 2.10 Embedding 与向量存储（4 个文件）

| 文件 | 类/函数 | 做了什么 | 调用了谁 |
|------|---------|---------|---------|
| `app/embeddings/vector_store.py` | `VectorStore.add_clauses()` | 批量 embed 条款文本 → 写入 ChromaDB collection，去重（同一 doc_id 不重复入库） | `embeddings.embedding_service`, `app.main.chroma_client` |
| | `similarity_search(query, doc_id, k)` | 用 query embedding 在 ChromaDB 做 ANN 检索，返回 top-k 条款+分数 | `embeddings.embedding_service` |
| | `delete_document(doc_id)` | 删除某文档的所有向量（按 doc_id 过滤） | ChromaDB |
| `app/embeddings/embedding_service.py` | `EmbeddingService` | 兼容包装器，委托给 `EmbeddingProviderFactory.create()` | `core.embedding_provider` |
| `app/embeddings/content_hash.py` | `clause_hash(text)` | SHA256 归一化文本，用于去重 | 无 |

---

### 2.11 Provider 抽象层（2 个文件）

| 文件 | 类 | 做了什么 |
|------|-----|---------|
| `app/core/llm_provider.py` | `BaseLLMProvider` | 抽象接口：`chat()`, `chat_json()`, `chat_with_cot()` |
| | `DeepSeekProvider` | OpenAI 协议兼容 client（`AsyncOpenAI`），CoT 通过"【推理过程】→【最终答案】" prompt 模式实现，内建缓存 |
| | `LLMProviderFactory` | 工厂模式：按 `settings.llm_provider` 创建实例，支持 `register()` 扩展 |
| `app/core/embedding_provider.py` | `SentenceTransformersProvider` | 本地模型 `paraphrase-multilingual-MiniLM-L12-v2`，通过 hf-mirror 下载 |
| | `OpenAIEmbeddingProvider` | OpenAI / DeepSeek Embedding API，`text-embedding-3-small` |
| | `EmbeddingProviderFactory` | 工厂模式：按 `settings.embedding_provider` 创建，支持扩展 |

---

### 2.12 文档解析与清洗（4 个文件）

文档从二进制到干净文本的完整链路：**文件校验 → 解析(PDF/DOCX/TXT) → 清洗(clean_document_text) → 条款分块(两级拆分)**。

| 文件 | 类 | 方法 | 做了什么 |
|------|-----|------|---------|
| `app/parser/document_parser.py` | `DocumentParserFactory.create()` | 按扩展名路由：`.pdf` → PdfParser, `.docx` → DocxParser, `.txt` → TxtParser |
| | `TxtParser` | `extract_text()` | 直接 `open().read()` |
| `app/parser/pdf_parser.py` | `PdfParser` | `extract_text()` | PyMuPDF 逐页提取 blocks，按 y 坐标排序 → `_process_page_blocks()` 检测表格行：同 y 坐标（容差 5pt）的多列块用 `|` 拼接保留列结构 |
| `app/parser/docx_parser.py` | `DocxParser` | `extract_text()` | 遍历 XML `doc.element.body` 按文档顺序交替提取段落 + 表格。表格通过 `_extract_table()` 转 Markdown 文本（首行表头 + 分隔线 + `|` 分隔列） |
| `app/parser/chunker.py` | `ClauseLevelChunker` | `split_clauses()` | **两级拆分**：主策略按"第X条/章/节"正则拆分 → **超过 2000 字的单条款触发次级拆分**（编号子项 `(1)/①/（一）` → 分号断句 → 硬截断）→ 后备按双换行拆分，过滤 <20 字碎片 |
| `app/utils/text_utils.py` | — | `clean_document_text()` | 上传时清洗：去除控制字符 → 统一换行符 → 合并连续空行 → 合并多余空格 → 去首尾空白。与安全管线的 filter_text 互补（前者只管格式，后者管安全） |
| | — | `truncate_head_tail()` | 头+尾截断策略：取文本前 70% + 省略标记 + 后 30%，保留尾部关键信息（违约责任、救济措施常在条款末尾） |

---

### 2.13 LLM 兼容层（2 个文件）

| 文件 | 做了什么 |
|------|---------|
| `app/llm/__init__.py` | 公开导出 `llm_client` |
| `app/llm/client.py` | `LlmClient` 兼容包装器：`chat()`, `chat_json()`, `chat_with_cot()` 三种接口，全部委托给 `LLMProviderFactory.create()`。agent 节点统一 `from app.llm.client import llm_client` |

---

### 2.14 工具类（5 个文件）

| 文件 | 导出 | 做了什么 |
|------|------|---------|
| `app/utils/jwt_utils.py` | `create_access_token()`, `create_refresh_token()`, `decode_token()`, `get_token_hash()` | JWT 签发（HS256）、验证、SHA256 哈希（黑名单用） |
| `app/utils/redis_utils.py` | `get_redis()` | Redis 连接池单例（懒加载），`decode_responses=True` |
| `app/utils/security.py` | `hash_password()`, `verify_password()` | bcrypt 密码哈希与验证 |
| `app/utils/json_utils.py` | `extract_json()`, `parse_json()` | 从 LLM 输出中提取 JSON：清除 markdown code fences、处理异常格式 |
| `app/utils/logger.py` | — | Python logging 配置（basicConfig） |
| `app/utils/text_utils.py` | `clean_document_text()` / `normalize_text()` / `truncate_head_tail()` / `truncate_text()` | 上传时文档清洗（去控制字符、统一换行符、合并空白）+ 头尾截断策略（保护尾部关键信息如违约责任条款） |

---

### 2.15 其他服务文件（2 个文件）

| 文件 | 导出 | 做了什么 |
|------|------|---------|
| `app/services/rate_limit_service.py` | `rate_limit(user_id, endpoint, max, window)` | Redis Lua 脚本实现 Token Bucket 限流，抛 `RateLimitExceededException` |
| `app/services/file_validator.py` | `validate(file_bytes, filename, content_type)` | 6 层文件校验：文件名安全→非空→扩展名白名单→大小上限→MIME 匹配→魔数校验 |
| `app/middleware/auth_middleware.py` | `get_current_user_id()`, `get_optional_user_id()` | FastAPI Depends：从 Bearer header 或 query param 提取 JWT，验证+黑名单检查后返回 user_id |

---

### 2.16 Pydantic Schema（8 个文件）

| 文件 | 定义了 |
|------|--------|
| `app/schemas/common.py` | `ApiResponse[T]` 统一响应格式：code + message + data |
| `app/schemas/auth.py` | `RegisterRequest`, `LoginRequest`, `RefreshRequest`, `LoginResponse`, `UserBrief` |
| `app/schemas/document.py` | `DocumentResponse` |
| `app/schemas/review.py` | `ReviewRequest`(内部), `ReviewResult`, `RiskItem`, `ReviewCreateRequest`(前端), `ReviewTaskResponse`, `ReviewResultResponse`, `RiskItemDto`, `ParseRequest/Response` |
| `app/schemas/consultation.py` | `ConsultationRequest/Response`, `ConsultationApiRequest`, `SourceClause` |
| `app/schemas/mcp.py` | `RegulationEntry`, `RegulationSearchResult`, `TemplateDeviation`, `TemplateCompareResult`, `ClauseModification`, `AmendmentResult`, `OneSidedClause`, `BalanceEvaluation` |
| `app/schemas/sse.py` | SSE 事件相关的模型 |
| `app/security/schemas.py` | `RiskClass`, `ApprovalType`, `ApprovalStatus`, `FilterResult`, `ClassifyResult`, `GuardResult`, `SecurityVerdict` |

---

## 三、前端文件详解（19 个文件）

### 3.1 入口与路由

| 文件 | 做了什么 | 路由 |
|------|---------|------|
| `frontend/src/main.tsx` | React 18 入口，挂载 App | — |
| `frontend/src/App.tsx` | 路由定义，ProtectedRoute 包裹 Layout 下的所有页面 | `/login`, `/register`, `/`(Dashboard), `/upload`, `/review/:taskId`, `/consult/:documentId` |

### 3.2 状态管理与 API

| 文件 | 做了什么 | 关键点 |
|------|---------|--------|
| `frontend/src/api/client.ts` | Axios 实例，自动 Bearer token 注入，401 时自动 refresh token（防并发），刷新失败直接踢到 `/login` | 拦截器机制 |
| `frontend/src/store/authStore.ts` | Zustand 状态：user + isLoggedIn + setUser + logout | localStorage 持久化 token |
| `frontend/src/hooks/useAuth.ts` | `useAuthStore()` 的薄包装 hook | — |
| `frontend/src/hooks/useSse.ts` | SSE 事件流 Hook，连接 `/reviews/{taskId}/stream`，解析事件更新进度 | EventSource |

### 3.3 页面组件

| 文件 | 对应路由 | 功能 |
|------|---------|------|
| `frontend/src/pages/LoginPage.tsx` | `/login` | 登录表单 → 调 POST `/auth/login` → 存 token → 跳首页 |
| `frontend/src/pages/RegisterPage.tsx` | `/register` | 注册表单 → 调 POST `/auth/register` |
| `frontend/src/pages/DashboardPage.tsx` | `/` | 审查任务列表 + 文档列表 tabs |
| `frontend/src/pages/DocumentUploadPage.tsx` | `/upload` | 拖拽上传 → 调 POST `/documents/upload` |
| `frontend/src/pages/ReviewPage.tsx` | `/review/:taskId` | 审查详情：SSE 实时进度 + 风险列表 |
| `frontend/src/pages/ConsultationPage.tsx` | `/consult/:documentId` | 智能问答界面：输入问题 → 调 POST `/consultations` → 显示回答+来源 |

### 3.4 共享组件

| 文件 | 功能 |
|------|------|
| `frontend/src/components/Layout.tsx` | 页面布局：Navbar + `<Outlet />` |
| `frontend/src/components/RiskItemCard.tsx` | 风险卡片：展示风险类型、等级、描述、修改建议、法律依据 |
| `frontend/src/components/ReviewProgress.tsx` | 审查进度条：已审查/总条款数 + 风险分布柱状图 |

### 3.5 类型定义

| 文件 | 内容 |
|------|------|
| `frontend/src/types/auth.ts` | LoginRequest, User |
| `frontend/src/types/document.ts` | DocumentResponse |
| `frontend/src/types/review.ts` | ReviewTaskResponse, RiskItemDto, ReviewResultResponse |
| `frontend/src/types/sse.ts` | SseEvent 类型 |

---

## 四、完整调用关系速查

### 一条 API 请求的完整路径

**用户上传文档：**
```
浏览器 → POST /api/v1/documents/upload
  → api/document_router.py: upload_document()
    → middleware/auth_middleware.py: get_current_user_id()  [JWT 验证 + Redis 黑名单]
    → services/file_validator.py: validate()                [6层文件校验]
    → parser/document_parser.py: DocumentParserFactory.create() → PdfParser(表格行检测)/DocxParser(表格提取)
    → utils/text_utils.py: clean_document_text()            [清洗：去控制字符、统一换行符、合并空白]
    → parser/chunker.py: ClauseLevelChunker.split_clauses() [两级条款拆分(含长条款次级拆分)]
    → models/__init__.py: Document(...)                     [写 MySQL — 此时 content_text 已清洗]
    → embeddings/vector_store.py: vector_store.add_clauses() [写 ChromaDB — 干净文本入库]
    → rag/hybrid_retriever.py: hybrid_retriever.index_clauses() [建 BM25 索引]
    → 返回 ApiResponse
```

**启动一次合同审查：**
```
浏览器 → POST /api/v1/reviews/reviews
  → api/review_router.py: create_review()
    → services/rate_limit_service.py: rate_limit()          [Token Bucket 限流]
    → services/review_service.py: ReviewService.create_review()
      → 验证 Document 归属（查 MySQL）
      → 创建 ReviewTask (status=PENDING)
      → asyncio.create_task(ReviewService._run_review())    [后台执行]
        → security/__init__.py: SecurityPipeline.check_document()  [四层安全防线]
        → 取 sanitized_text 作为 Agent 输入（安全清洗后的文本）
        → agent/state.py: create_initial_state(document_text=sanitized_text)
        → agent/graph.py: build_review_graph().compile().astream()
          → 7 个 agent/nodes/*_node.py 依次执行
          → 各节点通过 mcp/tools/*.py → security/tool_guard.py 调用工具（超长参数自动头尾截断）
        → sse_service.py: send_event() 推送实时事件
        → 写入 ReviewResult + RiskItem 到 MySQL
```

**智能问答：**
```
浏览器 → POST /api/v1/consultations
  → api/consultation_router.py: ask_question_api()
    → security/__init__.py: SecurityPipeline.check_query()  [L1+L2 安全]
    → rag/consultation_chain.py: answer_question()          [7步 RAG 管线]
      → rag/query_rewriter.py → rag/question_router.py
      → rag/hybrid_retriever.py (BM25 + ChromaDB 向量)
      → rag/secondary_retriever.py (低置信度触发)
      → rag/reranker.py (BGE CrossEncoder 精排)
      → rag/context_assembler.py (Token 预算打包)
      → llm/client.py (LLM 生成答案)
      → rag/citation_verifier.py (引用幻觉检测)
    → 写入 ConsultationRecord
    → 返回答案 + 来源条款 + 引用警告
```

### 文件间的 import 关系速查

```
main.py
 ├── config.py (settings)
 ├── database.py (init_db, engine)
 ├── api/router.py (api_router)
 └── core/{llm_provider, embedding_provider}.py

api/router.py
 ├── api/auth_router.py → services/auth_service.py → models/, utils/{security, jwt_utils, redis_utils}
 ├── api/document_router.py → services/document_service.py → models/, parser/, embeddings/, rag/
 ├── api/review_router.py → services/review_service.py → models/, agent/, security/, sse_service
 ├── api/consultation_router.py → services/consultation_service.py → models/, security/, rag/
 └── api/security_router.py → security/human_gate.py → models/

services/review_service.py (_run_review)
 ├── agent/state.py (create_initial_state)
 ├── agent/graph.py (build_review_graph)
 └── security/__init__.py (SecurityPipeline)

agent/graph.py
 ├── agent/state.py (AgentState)
 ├── agent/nodes/{parse, extract_clauses, risk_type_identify, severity_check,
 │              compliance_check, amendment_generate, aggregate_report}_node.py
 └── agent/edges/conditions.py

agent/nodes/severity_check_node.py
 ├── llm/client.py (llm_client)
 ├── mcp/tools/compare_template.py (handler)
 ├── security/tool_guard.py (guard_tool_call)

rag/consultation_chain.py
 ├── llm/client.py
 ├── rag/{query_rewriter, question_router, hybrid_retriever, secondary_retriever,
 │       reranker, context_assembler, citation_verifier}.py
 └── embeddings/vector_store.py

rag/hybrid_retriever.py
 ├── embeddings/vector_store.py
 └── rag/bm25_retriever.py

mcp/tools/search_regulations.py
 ├── embeddings/embedding_service.py
 └── schemas/mcp.py

security/__init__.py (SecurityPipeline)
 ├── security/rule_filter.py
 ├── security/risk_classifier.py → llm/client.py
 ├── security/human_gate.py → models/
 └── security/schemas.py

cache/__init__.py (CacheManager)
 ├── cache/memory_cache.py
 └── cache/redis_cache.py → utils/redis_utils.py

core/llm_provider.py (DeepSeekProvider)
 ├── config.py
 └── cache/__init__.py (cache_manager)

embeddings/vector_store.py
 ├── app/main.py (chroma_client)
 └── embeddings/embedding_service.py → core/embedding_provider.py
```

---

## 五、面试快速定位指南

| 面试问什么 | 看哪个文件 |
|-----------|-----------|
| LangGraph 审查管线怎么搭的 | `agent/graph.py`(图) + `agent/state.py`(状态) + `agent/edges/conditions.py`(分支) |
| 7 个节点分别做什么 | `agent/nodes/` 下各文件 |
| 每个节点如何调 LLM | `agent/nodes/risk_type_identify_node.py:53-56` → `llm/client.py:22-24` → `core/llm_provider.py:85-131` |
| CoT 思维链怎么实现 | `core/llm_provider.py:85-131` chat_with_cot() |
| MCP 工具体系怎么设计 | `core/tool_registry.py`(注册) + `mcp/mcp_server.py`(服务) + `mcp/tools/`(4个工具) |
| 4 个 MCP 工具各自做什么 | `mcp/tools/{search_regulations, compare_template, generate_amendment, evaluate_balance}.py` |
| 安全防线四层分别怎么实现 | `security/rule_filter.py`(L1) + `security/risk_classifier.py`(L2) + `security/tool_guard.py`(L3) + `security/human_gate.py`(L4) |
| 安全管线决策逻辑 | `security/__init__.py:30-165` SecurityPipeline.check_document/check_query |
| RAG 怎么做混合检索 | `rag/hybrid_retriever.py:38-103` RRF 融合 |
| 低置信度二次检索 | `rag/secondary_retriever.py` |
| 精排怎么实现 | `rag/reranker.py:76-89` BGE CrossEncoder |
| Context 怎么控制 Token | `rag/context_assembler.py:29-110` |
| 引用幻觉怎么检测 | `rag/citation_verifier.py` |
| 缓存双层怎么设计 | `cache/__init__.py`(管理器) + `cache/memory_cache.py`(L1 LRU) + `cache/redis_cache.py`(L2 Redis) |
| Provider 抽象层 | `core/llm_provider.py`(LLM) + `core/embedding_provider.py`(Embedding) |
| 数据库 8 张表怎么设计 | `models/__init__.py` + 本文档 2.2 节"数据库设计要点" |
| 文件上传怎么校验 | `services/file_validator.py` |
| 限流怎么实现 | `services/rate_limit_service.py` |
| AE 事件流怎么推送 | `services/sse_service.py` → `api/review_router.py:183-191` |
