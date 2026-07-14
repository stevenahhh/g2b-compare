"""Immutable local and G2B synchronization settings."""

from __future__ import annotations

from typing import ClassVar, Final, Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
)
from pydantic_core import PydanticCustomError
from pydantic_settings import BaseSettings, SettingsConfigDict

G2B_API_BASE_URL: Final = "https://apis.data.go.kr/1230000/ShoppingMallPrdctInfoService"
G2B_ITEM_LIST_URL: Final = f"{G2B_API_BASE_URL}/getShoppingMallPrdctInfoList01"
OFFICIAL_BASE_ERROR_CODE: Final = "official_https"
OFFICIAL_BASE_ERROR_MESSAGE: Final = (
    "production base must use the official HTTPS endpoint"
)


class ProductionBase(BaseModel):
    """Parsed immutable official production endpoint."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    url: AnyHttpUrl

    @field_validator("url")
    @classmethod
    def require_official_https(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        """Accept only the immutable official HTTPS service base."""
        if str(value).rstrip("/") != G2B_API_BASE_URL:
            raise PydanticCustomError(
                OFFICIAL_BASE_ERROR_CODE,
                OFFICIAL_BASE_ERROR_MESSAGE,
            )
        return value


class AppSettings(BaseSettings):
    """Frozen local application settings that require no remote secret."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="G2B_",
        extra="forbid",
        frozen=True,
    )

    bind_host: Literal["127.0.0.1"] = "127.0.0.1"
    bind_port: int = Field(default=8765, ge=1, le=65535)
    daily_api_budget: int = Field(default=1000, gt=0)


class SyncSettings(AppSettings):
    """Remote synchronization settings with a redacted required key."""

    service_key: SecretStr
