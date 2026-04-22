from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from backend.core.runtime_config import get_app_runtime_config
from backend.utils.storage import get_initial_data_dir, get_writable_base_dir

try:
    from pydantic.v1 import BaseSettings
except ImportError:
    from pydantic import BaseSettings


class Settings(BaseSettings):
    _runtime = get_app_runtime_config()

    app_name: str = _runtime.app_name
    host: str = _runtime.host
    port: int = 3000

    secret_key: str = _runtime.secret_key
    access_token_expire_hours: int = _runtime.access_token_expire_hours

    timezone: str = _runtime.timezone
    data_dir: Path = get_initial_data_dir()
    db_path: Optional[Path] = None
    signer_workdir: Optional[Path] = None
    session_dir: Optional[Path] = None
    logs_dir: Optional[Path] = None

    class Config:
        env_file = ".env"
        env_prefix = "APP_"
        case_sensitive = False

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.resolve_db_path()}?check_same_thread=False"

    def resolve_db_path(self) -> Path:
        return self.db_path or self.resolve_base_dir() / "db.sqlite"

    def resolve_workdir(self) -> Path:
        return self.signer_workdir or self.resolve_base_dir() / ".signer"

    def resolve_session_dir(self) -> Path:
        return self.session_dir or self.resolve_base_dir() / "sessions"

    def resolve_logs_dir(self) -> Path:
        return self.logs_dir or self.resolve_base_dir() / "logs"

    def resolve_base_dir(self) -> Path:
        if self.data_dir and str(self.data_dir) != "/data":
            return self.data_dir
        return get_writable_base_dir()


@lru_cache()
def get_settings() -> Settings:
    return Settings()
