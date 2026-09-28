from pydantic_settings import BaseSettings
from functools import lru_cache
from dotenv import load_dotenv

# LangSmith reads its config (LANGSMITH_*) from os.environ, not from Settings
load_dotenv()


class Settings(BaseSettings):
    groq_api_key: str
    primary_model: str = "openai/gpt-oss-120b"
    fallback_model:str = "openai/gpt-oss-20b"

    langsmith_tracing: bool = True
    langsmith_api_key: str = ""
    langsmith_project: str = "production-api"

    app_env: str = "development"
    log_level:str = "INFO"
    rate_limit: str = "20/minute"
    cache_ttl_seconds: int = 300
    max_retries: int = 3

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

@lru_cache
def get_settings() -> Settings:
    return Settings()
    