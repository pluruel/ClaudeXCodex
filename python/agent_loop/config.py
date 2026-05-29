"""Configuration helpers extracted from cli.py."""
from __future__ import annotations

from pathlib import Path

ArtifactMode = str


def _load_config(repo: Path) -> dict:
    import tomllib

    default_path = Path(__file__).resolve().parents[2] / "config" / "defaults.toml"
    data: dict = {}
    if default_path.exists():
        data = tomllib.loads(default_path.read_text(encoding="utf-8"))

    local_path = repo / ".agent-loop" / "config.toml"
    if local_path.exists():
        local = tomllib.loads(local_path.read_text(encoding="utf-8"))
        for key, value in local.items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key] = {**data[key], **value}
            else:
                data[key] = value
    return data


def _artifact_mode(cfg: dict) -> ArtifactMode:
    mode = cfg.get("artifacts", {}).get("mode", "compact")
    if mode not in ("compact", "debug"):
        raise ValueError(f"invalid artifacts.mode {mode!r}; expected 'compact' or 'debug'")
    return mode


def _worker_model_config(cfg: dict) -> tuple[list[str], str]:
    worker_cfg = cfg.get("worker_models", {})
    allowed = worker_cfg.get("allowed", ["haiku", "sonnet", "opus"])
    if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
        allowed = ["haiku", "sonnet", "opus"]
    default = worker_cfg.get("default", "sonnet")
    if default not in allowed:
        default = allowed[0] if allowed else "sonnet"
    return allowed, default


def _worker_reasoning_config(cfg: dict) -> tuple[list[str], str]:
    """Read `[worker_reasoning]` defaults and return ``(allowed, default)``.

    Mirrors the shape of ``_worker_model_config``. The reasoning axis is
    intentionally independent from model selection: a haiku subtask can still
    elect `high` effort if the few changes touch deep architecture, and an
    opus subtask can elect `low` if the changes are mostly mechanical.
    """
    reasoning_cfg = cfg.get("worker_reasoning", {})
    allowed = reasoning_cfg.get("allowed", ["low", "medium", "high"])
    if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
        allowed = ["low", "medium", "high"]
    default = reasoning_cfg.get("default", "medium")
    if default not in allowed:
        default = "medium" if "medium" in allowed else (allowed[0] if allowed else "medium")
    return allowed, default
