from __future__ import annotations

from app.config import ROOT, Settings, load_agent_config, load_prices


def test_agent_yaml_is_valid():
    cfg = load_agent_config(ROOT / "config" / "agent.yaml")
    assert cfg.models.chain[0].startswith("anthropic:") and cfg.limits.per_turn_usd < 1


def test_prices_cover_every_configured_model():
    cfg, prices = load_agent_config(), load_prices()
    for name in cfg.models.chain + [cfg.models.guard_decision, cfg.models.guard_fallback]:
        assert name.split(":", 1)[1] in prices, f"no price for {name}"


def test_key_lookup_by_vendor_prefix():
    s = Settings(_env_file=None, anthropic_api_key="a", typesafe_api_key="t")
    assert s.key_for("anthropic:claude-haiku-5-5") == "a" and s.key_for("typesafe:jev-latest") == "t"
    assert s.key_for("openai:gpt-5.2") is None and s.key_for("weird:model") is None
