"""Load the explicit YAML settings for a buy-and-hold run."""

from pathlib import Path

import yaml


CONFIG_KEYS = {
    "strategy", "csv", "interval", "market", "adjustment", "naive_timezone",
    "initial_cash", "shares", "commission_rate", "fixed_fee", "slippage_bps", "output_dir",
}


def load_strategy_config(path: str | Path) -> dict:
    """Read YAML; paths inside it are relative to the YAML file's directory."""
    path = Path(path).resolve()
    try:
        settings = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid strategy YAML: {exc}") from exc
    if not isinstance(settings, dict):
        raise ValueError("Strategy config must be a YAML mapping")
    unknown = set(settings) - CONFIG_KEYS
    if unknown:
        raise ValueError(f"Unknown strategy config keys: {', '.join(sorted(map(str, unknown)))}")
    if settings.get("strategy", "buy_and_hold") != "buy_and_hold":
        raise ValueError("Only the buy_and_hold strategy is implemented")
    if settings.get("csv") is None:
        raise ValueError("Strategy config must specify csv")
    for key in ("csv", "output_dir", "interval", "market", "adjustment", "naive_timezone"):
        value = settings.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"Config {key} must be a nonempty string or null")
    for key in ("csv", "output_dir"):
        if settings.get(key) is not None:
            settings[key] = (path.parent / settings[key]).resolve()
    return settings
