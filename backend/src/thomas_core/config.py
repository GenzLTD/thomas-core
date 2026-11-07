"""核自己的 Config（刀 5b：断 `src.config`）。

为什么需要：`src/config.py`（334 行）是**产品+核的合订本** —— 支付 / 快递 / 企查查 /
华为推送等产品侧键都在里面。核 import 它，独立发版 split 后新仓会缺文件；整包搬走
又会把产品 secret 面拖进核。所以核只保留**自己真正读的键**，取值语义与 `src.config.Config`
逐键一致（`tests/test_core_config_parity.py` 有一致性断言，改一边不改另一边会红）。

纪律：
- 只读，不新增开关；键名 / 默认值 / 类型转换与 `src.config.Config` 完全同源；
- 每次 `create_core_app()` 前调 `CoreConfig.refresh()`，让 per-test 的
  `DATABASE_PATH` 等 env 覆盖生效（对齐 `_refresh_config()` 的行为）。
"""
from __future__ import annotations

import os

# 与 `src.config` 同一行为：导入即加载 .env（不覆盖已存在的 env）。
# 独立核仓里 dotenv 若未安装，退化为只读进程环境 —— 不因缺这个可选依赖起不来。
try:  # pragma: no cover - 环境相关
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

_DEFAULT_CORS = (
    "http://localhost:5173,http://localhost:5174,http://localhost:3000,"
    "http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:3000"
)


class CoreConfig:
    """核侧 Flask config（`app.config.from_object(CoreConfig)`）。

    只含 auth / identity / compliance / rag / llm / quota 需要的键；产品侧支付、
    快递、企查查、推送等键**不在核配置面内**。
    """

    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    FLASK_ENV = os.getenv("FLASK_ENV", "development")

    # JWT
    JWT_SECRET = os.getenv("JWT_SECRET", "looma-zervi-default-jwt-secret-change-in-production-2026")
    JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

    # Supabase — THOMAS 生态统一认证
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
    SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
    SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
    SUPABASE_JWKS_URL = (
        os.getenv("SUPABASE_URL", "").rstrip("/") + "/auth/v1/.well-known/jwks.json"
    ) if os.getenv("SUPABASE_URL", "") else ""

    # 第三方登录
    WECHAT_APPID = os.getenv("WECHAT_APPID", "")
    WECHAT_APP_SECRET = os.getenv("WECHAT_APP_SECRET", "")
    WECHAT_DEV_MODE = os.getenv("WECHAT_DEV_MODE", "false").lower() == "true"
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")
    HUAWEI_CLIENT_ID = os.getenv("HUAWEI_CLIENT_ID", "")
    HUAWEI_CLIENT_SECRET = os.getenv("HUAWEI_CLIENT_SECRET", "")
    HUAWEI_OAUTH_REGION = os.getenv("HUAWEI_OAUTH_REGION", "cn")

    # LLM
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    LLM_PROVIDER_ORDER = os.getenv("LLM_PROVIDER_ORDER", "deepseek,ollama")
    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")

    # Embedding
    EMBED_PROVIDER_ORDER = os.getenv("EMBED_PROVIDER_ORDER", "openai,ollama,deepseek")
    EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text:latest")

    # RAG / ChromaDB
    CHROMA_MODE = os.getenv("CHROMA_MODE", "local")
    CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
    CHROMA_PORT = os.getenv("CHROMA_PORT", "8000")
    CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "looma_knowledge")
    POETRY_CHROMA_PATH = os.getenv("POETRY_CHROMA_PATH", "data/poetry_full")

    # SQLite — 动态读，tests 可 per-fixture 覆盖
    DATABASE_PATH = os.getenv("DATABASE_PATH", "data/looma.db")

    # CORS
    CORS_ORIGINS = [
        o.strip() for o in os.getenv("CORS_ORIGINS", _DEFAULT_CORS).split(",") if o.strip()
    ]

    # Quota
    FREE_DAILY_LIMIT = int(os.getenv("FREE_DAILY_LIMIT", "30"))
    SUPPORTER_DAILY_LIMIT = int(os.getenv("SUPPORTER_DAILY_LIMIT", "999999"))
    PRO_DAILY_LIMIT = int(os.getenv("PRO_DAILY_LIMIT", "999999"))

    # 跨产品身份桥（circle / ETHOS HS256）
    ETHOS_AUTH_SECRET = os.getenv("ETHOS_AUTH_SECRET", "").strip()

    @classmethod
    def refresh(cls) -> None:
        """重读 env 进类属性 —— 对齐 `src.config._refresh_config()` 的时点语义。"""
        cls.SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
        cls.FLASK_ENV = os.getenv("FLASK_ENV", "development")
        cls.JWT_SECRET = os.getenv(
            "JWT_SECRET", "looma-zervi-default-jwt-secret-change-in-production-2026"
        )
        cls.JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))
        cls.JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
        cls.SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
        cls.SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
        cls.SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "")
        cls.SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
        cls.SUPABASE_JWKS_URL = (
            os.getenv("SUPABASE_URL", "").rstrip("/") + "/auth/v1/.well-known/jwks.json"
        ) if os.getenv("SUPABASE_URL", "") else ""
        cls.WECHAT_APPID = os.getenv("WECHAT_APPID", "")
        cls.WECHAT_APP_SECRET = os.getenv("WECHAT_APP_SECRET", "")
        cls.WECHAT_DEV_MODE = os.getenv("WECHAT_DEV_MODE", "false").lower() == "true"
        cls.GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
        cls.GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
        cls.GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")
        cls.HUAWEI_CLIENT_ID = os.getenv("HUAWEI_CLIENT_ID", "")
        cls.HUAWEI_CLIENT_SECRET = os.getenv("HUAWEI_CLIENT_SECRET", "")
        cls.HUAWEI_OAUTH_REGION = os.getenv("HUAWEI_OAUTH_REGION", "cn")
        cls.DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
        cls.DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        cls.DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        cls.LLM_PROVIDER_ORDER = os.getenv("LLM_PROVIDER_ORDER", "deepseek,ollama")
        cls.OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        cls.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        cls.OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")
        cls.EMBED_PROVIDER_ORDER = os.getenv("EMBED_PROVIDER_ORDER", "openai,ollama,deepseek")
        cls.EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text:latest")
        cls.CHROMA_MODE = os.getenv("CHROMA_MODE", "local")
        cls.CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
        cls.CHROMA_PORT = os.getenv("CHROMA_PORT", "8000")
        cls.CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "looma_knowledge")
        cls.POETRY_CHROMA_PATH = os.getenv("POETRY_CHROMA_PATH", "data/poetry_full")
        cls.DATABASE_PATH = os.getenv("DATABASE_PATH", "data/looma.db")
        cls.CORS_ORIGINS = [
            o.strip() for o in os.getenv("CORS_ORIGINS", _DEFAULT_CORS).split(",") if o.strip()
        ]
        cls.FREE_DAILY_LIMIT = int(os.getenv("FREE_DAILY_LIMIT", "30"))
        cls.SUPPORTER_DAILY_LIMIT = int(os.getenv("SUPPORTER_DAILY_LIMIT", "999999"))
        cls.PRO_DAILY_LIMIT = int(os.getenv("PRO_DAILY_LIMIT", "999999"))
        cls.ETHOS_AUTH_SECRET = os.getenv("ETHOS_AUTH_SECRET", "").strip()
