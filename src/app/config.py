"""Configuration: secrets from the environment, everything else from config/agent.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import AliasChoices, BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


class ModelsConfig(BaseModel):
    chain: list[str] = Field(min_length=1)
    guard_decision: str
    guard_fallback: str
    guard_confidence: float = Field(ge=0.0, le=1.0)
    timeout_s: float = Field(gt=0)
    retry_attempts: int = Field(ge=1)
    retry_max_wait_s: float = Field(ge=0)
    cache: bool = True  # Anthropic prompt caching of instructions, tool definitions and messages


class LimitsConfig(BaseModel):
    max_message_chars: int = Field(gt=0)
    max_turns: int = Field(gt=0)
    model_requests_per_turn: int = Field(gt=0)
    per_turn_usd: float = Field(gt=0)
    per_turn_estimate_usd: float = Field(gt=0)
    per_ip_per_hour: int = Field(gt=0)
    global_per_day: int = Field(gt=0)
    session_ttl_s: float = Field(gt=0)


class AgentConfig(BaseModel):
    version: str
    name: str
    models: ModelsConfig
    limits: LimitsConfig


class Price(BaseModel):
    input: float = Field(ge=0)
    output: float = Field(ge=0)


def load_agent_config(path: Path = CONFIG_DIR / "agent.yaml") -> AgentConfig:
    return AgentConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_prices(path: Path = CONFIG_DIR / "prices.yaml") -> dict[str, Price]:
    """Model rows only; scalar keys such as `version` are metadata (see prices_version)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {name: Price.model_validate(p) for name, p in raw.items() if isinstance(p, dict)}


def prices_version(path: Path = CONFIG_DIR / "prices.yaml") -> str:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return str(raw["version"])


class Settings(BaseSettings):
    """Secrets and deployment knobs. Read once at startup; never logged."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True)

    # AIRPORTIQ_-prefixed names win over the plain ones: shared cloud environments withhold ANTHROPIC_API_KEY.
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("AIRPORTIQ_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"))
    google_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("AIRPORTIQ_GOOGLE_API_KEY", "GOOGLE_API_KEY"))
    openrouter_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("AIRPORTIQ_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"))
    typesafe_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("AIRPORTIQ_TYPESAFE_API_KEY", "TYPESAFE_API_KEY"))
    opensky_client_id: SecretStr | None = None  # OpenSky registered client; anonymous (400 credits/day) when unset
    opensky_client_secret: SecretStr | None = None
    opensky_cache_min: int = Field(default=2, ge=1)
    budget_usd: float = Field(default=15.0, gt=0)
    db_path: Path = Path("data/agent.db")
    admin_token: SecretStr | None = None
    model_mode: str = "live"  # "test" answers every call offline with TestModel
    port: int = 8000
    faa_user_agent: str = "Mozilla/5.0 airportiq/0.1 (github.com/ozeriyarin/airportiq)"  # faa.gov rejects bare UAs
    snapshot_dir: Path = Path("data/snapshots")
    live_cache_min: int = Field(default=10, ge=1)

    def key_for(self, model_name: str) -> str | None:
        """The vendor key a Pydantic AI model string needs, or None when it is not set."""
        prefix = model_name.split(":", 1)[0]
        secret = {
            "anthropic": self.anthropic_api_key,
            "google-gla": self.google_api_key,
            "google-vertex": self.google_api_key,
            "openrouter": self.openrouter_api_key,
            "typesafe": self.typesafe_api_key,
        }.get(prefix)
        return secret.get_secret_value() if secret else None

    @staticmethod
    def reveal(secret: SecretStr | None) -> str | None:
        return secret.get_secret_value() if secret else None
