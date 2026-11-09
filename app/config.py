from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QMS_", env_file=".env", extra="ignore")
    data_dir: Path = Path("data")
    max_upload_mb: int = Field(default=10, ge=1, le=100)
    ai_provider: Literal["mock", "local", "cloud"] = "mock"
    local_model: str = ""
    cloud_service: Literal["deepseek", "groq"] = "deepseek"
    cloud_model: str = Field(default="deepseek-chat", max_length=100)
    cloud_endpoint: str = "https://api.deepseek.com/chat/completions"
    cloud_enabled: bool = False
    cloud_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    local_endpoint: str = "http://127.0.0.1:1234/v1/chat/completions"
    ai_timeout_seconds: int = Field(default=20, ge=5, le=60)
    ai_max_tokens: int = Field(default=512, ge=32, le=2048)
