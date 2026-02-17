from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class DatabaseSettings(BaseSettings):
    sqlite_path: str = Field(default="db/xaloc_database.db", alias="SQLITE_DB_PATH")
    sqlserver_connection_string: Optional[str] = Field(default=None, alias="SQLSERVER_CONNECTION_STRING")

    # Fallback SQL Server fields if connection string is not set
    sqlserver_server: Optional[str] = Field(default=None, alias="SQLSERVER_SERVER")
    sqlserver_database: Optional[str] = Field(default=None, alias="SQLSERVER_DATABASE")
    sqlserver_username: Optional[str] = Field(default=None, alias="SQLSERVER_USERNAME")
    sqlserver_password: Optional[str] = Field(default=None, alias="SQLSERVER_PASSWORD")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

class XviaSettings(BaseSettings):
    email: Optional[str] = Field(default=None, alias="XVIA_EMAIL")
    password: Optional[str] = Field(default=None, alias="XVIA_PASSWORD")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

class BrainSettings(BaseSettings):
    sync_interval: int = Field(default=500, alias="BRAIN_SYNC_INTERVAL")
    tick_seconds: int = Field(default=5, alias="BRAIN_TICK_SECONDS")
    max_claims: int = Field(default=999999, alias="BRAIN_MAX_CLAIMS")
    target_queue_depth: int = Field(default=50, alias="BRAIN_TARGET_QUEUE_DEPTH")
    enabled_sites: str = Field(default="", alias="BRAIN_ENABLED_SITES")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

class WorkerSettings(BaseSettings):
    heartbeat_seconds: int = Field(default=5, alias="WORKER_HEARTBEAT_SECONDS")
    heartbeat_timeout: int = Field(default=90, alias="WORKER_HEARTBEAT_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

class AppSettings(BaseSettings):
    """
    Main configuration kernel.
    Access it via `config.database.sqlite_path` etc.
    """
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    xvia: XviaSettings = Field(default_factory=XviaSettings)
    brain: BrainSettings = Field(default_factory=BrainSettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

# Singleton instance
try:
    config = AppSettings()
except Exception as e:
    # Fail fast if critical config is missing (e.g. XVIA credentials)
    # But allow import for testing even if env is partial
    print(f"!! CONFIG WARNING: {e}")
    # Provide a partial/safe fallback if loading fails, or let it crash depending on philosophy
    # Here we instantiate with defaults (which might fail validation if required fields are missing)
    # So for now, we just print the error. The import will technically succeed if we set config=None or a dummy.
    # But we want 'config' to be available.

    # Re-raising would stop the app, which is often correct for production but annoying for partial tests.
    # Let's try to construct it with empty env if file fails
    config = AppSettings(_env_file=None)
