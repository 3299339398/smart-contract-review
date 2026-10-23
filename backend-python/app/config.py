from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ChromaDB 向量数据库
    chroma_host: str = "127.0.0.1"
    chroma_port: int = 8001

    # 大语言模型
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    log_level: str = "INFO"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    # 提供者选择
    llm_provider: str = "deepseek"           # deepseek | openai | local
    embedding_provider: str = "sentence_transformers"  # sentence_transformers | openai
    vector_store_provider: str = "chromadb"  # chromadb | qdrant

    # 缓存过期时间
    llm_cache_ttl: int = 3600               # LLM 响应缓存（1小时）
    rag_cache_ttl: int = 600                 # RAG 查询缓存（10分钟）
    review_cache_ttl: int = 3600            # 审查结果缓存（1小时）
    langgraph_checkpoint_path: str = "./data/checkpoints.sqlite"

    # ── RAG 检索管线 ───────────────────────────────────
    # 查询改写
    rag_query_rewrite_enabled: bool = True
    rag_query_rewrite_llm: bool = False     # 基于 LLM 的查询改写（消耗 API 调用）
    rag_query_rewrite_max_variants: int = 3

    # 问题路由
    rag_question_routing_enabled: bool = True
    rag_question_routing_llm: bool = False  # 基于 LLM 的问题分类

    # 混合检索权重
    rag_default_vector_weight: float = 0.7
    rag_default_bm25_weight: float = 0.3
    rag_rrf_k: int = 60

    # 重排序
    rag_rerank_enabled: bool = True
    rag_rerank_strategy: str = "cross_encoder"  # cross_encoder | llm | none
    rag_rerank_candidate_pool_size: int = 15

    # 上下文拼装
    rag_context_max_tokens: int = 2500
    rag_context_clause_max_chars: int = 500

    # 引用校验
    rag_citation_verify_enabled: bool = True

    # 二级检索
    rag_secondary_enabled: bool = True
    rag_secondary_score_threshold: float = 0.05
    rag_secondary_strategy: str = "query_expansion"

    # MySQL 数据库
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3307
    mysql_user: str = "scr_user"
    mysql_password: str = ""
    mysql_database: str = "contract_review"

    # Redis 缓存
    redis_host: str = "127.0.0.1"
    redis_port: int = 6380
    redis_password: str = ""

    # JWT 认证
    jwt_secret: str = ""
    jwt_expiration_ms: int = 3600000

    # 文件上传
    upload_dir: str = "./uploads"

    class Config:
        env_file = ".env"


settings = Settings()
