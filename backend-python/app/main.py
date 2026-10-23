from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.api.router import api_router
from app.config import settings
import chromadb
import logging

logging.basicConfig(level=getattr(logging, settings.log_level.upper()))
logger = logging.getLogger(__name__)

chroma_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global chroma_client
    # 初始化 ChromaDB 向量数据库
    try:
        chroma_client = chromadb.HttpClient(
            host=settings.chroma_host, port=settings.chroma_port
        )
        chroma_client.heartbeat()
        logger.info(f"ChromaDB connected at {settings.chroma_host}:{settings.chroma_port}")
    except Exception as e:
        logger.warning(f"ChromaDB not available: {e}, using ephemeral client")
        chroma_client = chromadb.EphemeralClient()
        #连接向量数据库

    # 初始化 MySQL 数据库
    try:
        from app.database import init_db
        await init_db()
        logger.info("MySQL tables initialized")
    except Exception as e:
        logger.warning(f"MySQL initialization skipped: {e}")

    # 初始化 LLM/Embedding 提供者
    try:
        from app.core.llm_provider import LLMProviderFactory
        from app.core.embedding_provider import EmbeddingProviderFactory
        LLMProviderFactory.create()
        EmbeddingProviderFactory.create()
        logger.info(f"Providers initialized: llm={settings.llm_provider}, "
                    f"embedding={settings.embedding_provider}")
    except Exception as e:
        logger.warning(f"Provider initialization skipped: {e}")

    yield

    # 清理资源
    try:
        from app.agent.checkpoint import close_checkpoint_saver
        await close_checkpoint_saver()
    except Exception:
        pass
    try:
        from app.database import engine
        await engine.dispose()
    except Exception:
        pass


app = FastAPI(
    title="Contract Review AI Service",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/")
def root():
    return {"service": "Contract Review AI", "status": "running"}


@app.get("/health")
def health():
    return {"status": "UP"}
