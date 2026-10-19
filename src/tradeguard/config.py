from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRADEGUARD_", env_file=".env", extra="ignore")

    database_url: SecretStr = SecretStr(
        "mysql+pymysql://tradeguard:tradeguard@127.0.0.1:53306/tradeguard?charset=utf8mb4"
    )
    selection_source_url: SecretStr | None = None
    portfolio_source_url: SecretStr | None = None
    migration_source_url: SecretStr | None = None
    longbridge_app_key: SecretStr | None = None
    longbridge_app_secret: SecretStr | None = None
    longbridge_access_token: SecretStr | None = None
    longbridge_region: str = "cn"
    futu_host: str = "127.0.0.1"
    futu_port: int = 11111
    futu_acc_id: str | None = None
    futu_markets: str = "US,HK"
    futu_security_firm: str = "FUTUSECURITIES"


def settings() -> Settings:
    return Settings()
