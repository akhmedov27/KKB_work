from pathlib import Path
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QMS_", env_file=".env", extra="ignore")
    data_dir: Path = Path("data")
    max_upload_mb: int = Field(default=10, ge=1, le=100)
    ai_provider: Literal["mock", "local", "cloud"] = "mock"
    local_model: str = ""
    cloud_model: str = ""
    cloud_endpoint: str = ""
