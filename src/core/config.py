"""Config loading and validation. Contract: contracts/s-1-foundation.contract.md"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_MAX_CONFIG_SIZE = 4096
_VALID_PROVIDERS = ("gemini", "lmstudio", "ask")


@dataclass
class Config:
    vault_path: str = ""
    sources_path: str = ""
    default_provider: str = "gemini"
    lmstudio_endpoint: str = "http://localhost:1234/v1"
    gemini_model: str = "gemini-3-flash-preview"
    chunk_threshold_lmstudio: int = 4000
    chunk_threshold_gemini: int = 750000
    chunk_overlap: int = 200
    graph_infer_confidence_threshold: float = 0.5


def _fail(msg: str) -> None:
    sys.exit(msg)


def load_config(path: str = "config.json") -> Config:
    p = Path(path)

    if not p.exists():
        _fail(f"Config file not found: {path}")

    size = p.stat().st_size
    if size > _MAX_CONFIG_SIZE:
        _fail(f"Config file too large ({size} bytes). Maximum is {_MAX_CONFIG_SIZE} bytes (4 KB).")

    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _fail(f"Config file contains invalid JSON: {e}")

    if not isinstance(data, dict):
        _fail("Config file must contain a JSON object.")

    _validate_required(data)
    _validate_types(data)
    _validate_values(data)

    known = {f for f in Config.__dataclass_fields__}
    filtered = {k: v for k, v in data.items() if k in known}
    return Config(**filtered)


def _validate_required(data: dict) -> None:
    for field_name in ("vault_path", "sources_path"):
        if field_name not in data:
            _fail(f"Missing required config field: {field_name}")


_FIELD_TYPES = {
    "vault_path": str,
    "sources_path": str,
    "default_provider": str,
    "lmstudio_endpoint": str,
    "gemini_model": str,
    "chunk_threshold_lmstudio": int,
    "chunk_threshold_gemini": int,
    "chunk_overlap": int,
    "graph_infer_confidence_threshold": (int, float),
}


def _validate_types(data: dict) -> None:
    for field_name, expected in _FIELD_TYPES.items():
        if field_name not in data:
            continue
        val = data[field_name]
        if isinstance(expected, tuple):
            if not isinstance(val, expected):
                type_names = " or ".join(t.__name__ for t in expected)
                _fail(f"Config field '{field_name}' must be {type_names}, got {type(val).__name__}.")
        else:
            if expected is int and isinstance(val, bool):
                _fail(f"Config field '{field_name}' must be int, got bool.")
            if not isinstance(val, expected):
                _fail(f"Config field '{field_name}' must be {expected.__name__}, got {type(val).__name__}.")


def _validate_values(data: dict) -> None:
    for str_field in ("vault_path", "sources_path"):
        if str_field in data and data[str_field] == "":
            _fail(f"Config field '{str_field}' must be non-empty.")

    if "gemini_model" in data and data["gemini_model"] == "":
        _fail("Config field 'gemini_model' must be non-empty.")

    if "default_provider" in data and data["default_provider"] not in _VALID_PROVIDERS:
        _fail(
            f"Config field 'default_provider' has invalid value '{data['default_provider']}'. "
            f"Valid options: {', '.join(_VALID_PROVIDERS)}."
        )

    if "lmstudio_endpoint" in data:
        ep = data["lmstudio_endpoint"]
        if not (ep.startswith("http://") or ep.startswith("https://")):
            _fail(f"Config field 'lmstudio_endpoint' must start with http:// or https://.")

    for threshold_field, max_val in [
        ("chunk_threshold_lmstudio", 1_000_000),
        ("chunk_threshold_gemini", 10_000_000),
    ]:
        if threshold_field in data:
            v = data[threshold_field]
            if v < 100:
                _fail(f"Config field '{threshold_field}' must be >= 100, got {v}.")
            if v > max_val:
                _fail(f"Config field '{threshold_field}' must be <= {max_val:,}, got {v}.")

    if "chunk_overlap" in data:
        overlap = data["chunk_overlap"]
        if overlap < 0:
            _fail(f"Config field 'chunk_overlap' must be non-negative, got {overlap}.")

    ct_lm = data.get("chunk_threshold_lmstudio", 4000)
    ct_gem = data.get("chunk_threshold_gemini", 750000)
    overlap = data.get("chunk_overlap", 200)
    smallest = min(ct_lm, ct_gem)
    if overlap >= smallest:
        _fail(
            f"Config field 'chunk_overlap' ({overlap}) must be less than the smallest "
            f"chunk threshold ({smallest})."
        )

    if "graph_infer_confidence_threshold" in data:
        v = data["graph_infer_confidence_threshold"]
        if v < 0.0 or v > 1.0:
            _fail(f"Config field 'graph_infer_confidence_threshold' must be 0.0–1.0, got {v}.")


def load_env(provider: str = "gemini") -> dict[str, str]:
    load_dotenv()
    env = {}
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        env["GEMINI_API_KEY"] = key
    if provider == "gemini" and not key:
        _fail(
            "Missing environment variable: GEMINI_API_KEY. "
            "Set it in .env or your shell environment."
        )
    return env
