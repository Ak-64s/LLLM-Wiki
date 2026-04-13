"""S-1 Foundation tests. Contract: contracts/s-1-foundation.contract.md"""

import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import requests

from src.core.config import Config, load_config, load_env
from src.core.provider import select_provider, check_lmstudio, ensure_provider_ready
from src.core.dirs import ensure_directories


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _valid_config(tmp_path: Path) -> dict:
    return {
        "vault_path": str(tmp_path / "vault"),
        "sources_path": str(tmp_path / "sources"),
    }


def _full_config(tmp_path: Path) -> dict:
    return {
        "vault_path": str(tmp_path / "vault"),
        "sources_path": str(tmp_path / "sources"),
        "default_provider": "gemini",
        "lmstudio_endpoint": "http://localhost:1234/v1",
        "gemini_model": "gemini-3-flash-preview",
        "chunk_threshold_lmstudio": 4000,
        "chunk_threshold_gemini": 750000,
        "chunk_overlap": 200,
        "graph_infer_confidence_threshold": 0.5,
    }


def _exit_msg(exc_info) -> str:
    """Extract the error message from a SystemExit, regardless of whether
    code is a string (sys.exit(msg)) or int (sys.exit(1))."""
    return str(exc_info.value.code) if exc_info.value.code is not None else ""


# ===========================================================================
# CONFIG LOADING — Happy Path
# ===========================================================================

class TestConfigHappy:
    # T-1.01
    def test_load_valid_config_all_fields(self, tmp_path):
        data = _full_config(tmp_path)
        cfg = load_config(str(_write_config(tmp_path, data)))
        assert cfg.vault_path == data["vault_path"]
        assert cfg.sources_path == data["sources_path"]
        assert cfg.default_provider == "gemini"
        assert cfg.lmstudio_endpoint == "http://localhost:1234/v1"
        assert cfg.gemini_model == "gemini-3-flash-preview"
        assert cfg.chunk_threshold_lmstudio == 4000
        assert cfg.chunk_threshold_gemini == 750000
        assert cfg.chunk_overlap == 200
        assert cfg.graph_infer_confidence_threshold == 0.5

    # T-1.02
    def test_load_config_required_fields_only(self, tmp_path):
        data = _valid_config(tmp_path)
        cfg = load_config(str(_write_config(tmp_path, data)))
        assert cfg.vault_path == data["vault_path"]
        assert cfg.sources_path == data["sources_path"]
        assert cfg.default_provider == "gemini"
        assert cfg.lmstudio_endpoint == "http://localhost:1234/v1"
        assert cfg.gemini_model == "gemini-3-flash-preview"
        assert cfg.chunk_threshold_lmstudio == 4000
        assert cfg.chunk_threshold_gemini == 750000
        assert cfg.chunk_overlap == 200
        assert cfg.graph_infer_confidence_threshold == 0.5

    # T-1.03
    def test_load_env_with_key_set(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        result = load_env()
        assert result == {"GEMINI_API_KEY": "test-key"}


# ===========================================================================
# CONFIG LOADING — Edge Cases
# ===========================================================================

class TestConfigEdge:
    # T-1.04
    def test_extra_unknown_fields_ignored(self, tmp_path):
        data = _valid_config(tmp_path)
        data["foo"] = "bar"
        data["unknown_field"] = 42
        cfg = load_config(str(_write_config(tmp_path, data)))
        assert cfg.vault_path == data["vault_path"]

    # T-1.05
    def test_chunk_overlap_zero(self, tmp_path):
        data = _valid_config(tmp_path)
        data["chunk_overlap"] = 0
        cfg = load_config(str(_write_config(tmp_path, data)))
        assert cfg.chunk_overlap == 0

    # T-1.06a
    def test_confidence_threshold_zero(self, tmp_path):
        data = _valid_config(tmp_path)
        data["graph_infer_confidence_threshold"] = 0.0
        cfg = load_config(str(_write_config(tmp_path, data)))
        assert cfg.graph_infer_confidence_threshold == 0.0

    # T-1.06b
    def test_confidence_threshold_one(self, tmp_path):
        data = _valid_config(tmp_path)
        data["graph_infer_confidence_threshold"] = 1.0
        cfg = load_config(str(_write_config(tmp_path, data)))
        assert cfg.graph_infer_confidence_threshold == 1.0

    # T-1.07
    def test_paths_with_spaces(self, tmp_path):
        data = {
            "vault_path": str(tmp_path / "my vault"),
            "sources_path": str(tmp_path / "my sources"),
        }
        cfg = load_config(str(_write_config(tmp_path, data)))
        assert cfg.vault_path == str(tmp_path / "my vault")

    # T-1.08
    def test_env_key_from_shell_no_dotenv(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GEMINI_API_KEY", "shell-key")
        monkeypatch.chdir(tmp_path)
        result = load_env()
        assert result["GEMINI_API_KEY"] == "shell-key"


# ===========================================================================
# CONFIG LOADING — Failure Cases
# ===========================================================================

class TestConfigFailure:
    # T-1.09
    def test_file_not_found(self):
        with pytest.raises(SystemExit) as exc_info:
            load_config("/nonexistent/path/config.json")
        msg = _exit_msg(exc_info)
        assert "not found" in msg.lower() or "config.json" in msg

    # T-1.10
    def test_invalid_json(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text("{broken json", encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(p))
        assert "invalid JSON" in _exit_msg(exc_info)

    # T-1.11
    def test_missing_vault_path(self, tmp_path):
        data = {"sources_path": str(tmp_path / "sources")}
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(_write_config(tmp_path, data)))
        assert "vault_path" in _exit_msg(exc_info)

    # T-1.12
    def test_missing_sources_path(self, tmp_path):
        data = {"vault_path": str(tmp_path / "vault")}
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(_write_config(tmp_path, data)))
        assert "sources_path" in _exit_msg(exc_info)

    # T-1.13
    def test_wrong_type_vault_path_int(self, tmp_path):
        data = _valid_config(tmp_path)
        data["vault_path"] = 123
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(_write_config(tmp_path, data)))
        msg = _exit_msg(exc_info)
        assert "vault_path" in msg
        assert "str" in msg

    # T-1.14
    def test_wrong_type_chunk_threshold_str(self, tmp_path):
        data = _valid_config(tmp_path)
        data["chunk_threshold_lmstudio"] = "4000"
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(_write_config(tmp_path, data)))
        msg = _exit_msg(exc_info)
        assert "chunk_threshold_lmstudio" in msg
        assert "int" in msg

    # T-1.15
    def test_chunk_threshold_below_minimum(self, tmp_path):
        data = _valid_config(tmp_path)
        data["chunk_threshold_lmstudio"] = 50
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(_write_config(tmp_path, data)))
        assert "100" in _exit_msg(exc_info)

    # T-1.16
    def test_chunk_threshold_above_maximum(self, tmp_path):
        data = _valid_config(tmp_path)
        data["chunk_threshold_gemini"] = 99999999
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(_write_config(tmp_path, data)))
        msg = _exit_msg(exc_info)
        assert "10,000,000" in msg or "10000000" in msg

    # T-1.17
    def test_confidence_threshold_out_of_range(self, tmp_path):
        data = _valid_config(tmp_path)
        data["graph_infer_confidence_threshold"] = 1.5
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(_write_config(tmp_path, data)))
        assert "0.0" in _exit_msg(exc_info) or "1.0" in _exit_msg(exc_info)

    # T-1.18
    def test_chunk_overlap_exceeds_threshold(self, tmp_path):
        data = _valid_config(tmp_path)
        data["chunk_overlap"] = 5000
        data["chunk_threshold_lmstudio"] = 4000
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(_write_config(tmp_path, data)))
        assert "overlap" in _exit_msg(exc_info).lower()

    # T-1.19
    def test_empty_vault_path(self, tmp_path):
        data = _valid_config(tmp_path)
        data["vault_path"] = ""
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(_write_config(tmp_path, data)))
        assert "vault_path" in _exit_msg(exc_info)

    # T-1.20
    def test_invalid_default_provider(self, tmp_path):
        data = _valid_config(tmp_path)
        data["default_provider"] = "openai"
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(_write_config(tmp_path, data)))
        assert "openai" in _exit_msg(exc_info)

    # T-1.21
    def test_endpoint_missing_http_prefix(self, tmp_path):
        data = _valid_config(tmp_path)
        data["lmstudio_endpoint"] = "localhost:1234"
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(_write_config(tmp_path, data)))
        assert "http" in _exit_msg(exc_info).lower()

    # T-1.22
    def test_config_file_exceeds_4kb(self, tmp_path):
        p = tmp_path / "config.json"
        data = _valid_config(tmp_path)
        data["padding"] = "x" * 5000
        p.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(p))
        msg = _exit_msg(exc_info)
        assert "too large" in msg.lower() or "4" in msg

    # T-1.23
    def test_missing_gemini_api_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            load_env(provider="gemini")
        assert "GEMINI_API_KEY" in _exit_msg(exc_info)

    # T-1.23b
    def test_missing_gemini_key_ok_for_lmstudio(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = load_env(provider="lmstudio")
        assert "GEMINI_API_KEY" not in result


# ===========================================================================
# PROVIDER SELECTION — Happy Path
# ===========================================================================

class TestProviderHappy:
    # T-1.24
    def test_select_gemini_from_config(self, tmp_path):
        data = _valid_config(tmp_path)
        data["default_provider"] = "gemini"
        cfg = load_config(str(_write_config(tmp_path, data)))
        assert select_provider(cfg) == "gemini"

    # T-1.25
    def test_select_lmstudio_from_config(self, tmp_path):
        data = _valid_config(tmp_path)
        data["default_provider"] = "lmstudio"
        cfg = load_config(str(_write_config(tmp_path, data)))
        assert select_provider(cfg) == "lmstudio"

    # T-1.26
    def test_check_lmstudio_reachable(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("src.core.provider.requests.get", return_value=mock_resp):
            assert check_lmstudio("http://localhost:1234/v1") is True

    # T-1.27
    def test_ensure_gemini_ready_no_check(self, tmp_path):
        data = _valid_config(tmp_path)
        cfg = load_config(str(_write_config(tmp_path, data)))
        assert ensure_provider_ready("gemini", cfg) == "gemini"

    # T-1.28
    def test_ensure_lmstudio_ready_reachable(self, tmp_path):
        data = _valid_config(tmp_path)
        cfg = load_config(str(_write_config(tmp_path, data)))
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("src.core.provider.requests.get", return_value=mock_resp):
            assert ensure_provider_ready("lmstudio", cfg) == "lmstudio"


# ===========================================================================
# PROVIDER SELECTION — Edge Cases
# ===========================================================================

class TestProviderEdge:
    # T-1.29
    def test_interactive_select_gemini(self, tmp_path):
        data = _valid_config(tmp_path)
        data["default_provider"] = "ask"
        cfg = load_config(str(_write_config(tmp_path, data)))
        with patch("builtins.input", return_value="1"):
            assert select_provider(cfg) == "gemini"

    # T-1.30
    def test_interactive_select_lmstudio(self, tmp_path):
        data = _valid_config(tmp_path)
        data["default_provider"] = "ask"
        cfg = load_config(str(_write_config(tmp_path, data)))
        with patch("builtins.input", return_value="2"):
            assert select_provider(cfg) == "lmstudio"

    # T-1.31
    def test_interactive_invalid_then_valid(self, tmp_path):
        data = _valid_config(tmp_path)
        data["default_provider"] = "ask"
        cfg = load_config(str(_write_config(tmp_path, data)))
        with patch("builtins.input", side_effect=["3", "1"]):
            assert select_provider(cfg) == "gemini"


# ===========================================================================
# PROVIDER SELECTION — Failure Cases
# ===========================================================================

class TestProviderFailure:
    # T-1.32
    def test_lmstudio_connection_refused(self):
        with patch("src.core.provider.requests.get", side_effect=requests.ConnectionError):
            assert check_lmstudio("http://localhost:1234/v1") is False

    # T-1.33
    def test_lmstudio_timeout(self):
        with patch("src.core.provider.requests.get", side_effect=requests.Timeout):
            assert check_lmstudio("http://localhost:1234/v1") is False

    # T-1.34
    def test_lmstudio_returns_500(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("src.core.provider.requests.get", return_value=mock_resp):
            assert check_lmstudio("http://localhost:1234/v1") is False

    # T-1.35
    def test_ad9_retry_then_success(self, tmp_path):
        data = _valid_config(tmp_path)
        cfg = load_config(str(_write_config(tmp_path, data)))

        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200

        call_count = 0
        def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise requests.ConnectionError
            return mock_resp_ok

        with patch("src.core.provider.requests.get", side_effect=mock_get):
            with patch("builtins.input", return_value=""):
                result = ensure_provider_ready("lmstudio", cfg)
        assert result == "lmstudio"

    # T-1.36
    def test_ad9_switch_to_gemini(self, tmp_path):
        data = _valid_config(tmp_path)
        cfg = load_config(str(_write_config(tmp_path, data)))
        with patch("src.core.provider.requests.get", side_effect=requests.ConnectionError):
            with patch("builtins.input", return_value="switch"):
                result = ensure_provider_ready("lmstudio", cfg)
        assert result == "gemini"

    # T-1.37
    def test_ad9_switch_case_insensitive(self, tmp_path):
        data = _valid_config(tmp_path)
        cfg = load_config(str(_write_config(tmp_path, data)))
        with patch("src.core.provider.requests.get", side_effect=requests.ConnectionError):
            with patch("builtins.input", return_value="SWITCH"):
                result = ensure_provider_ready("lmstudio", cfg)
        assert result == "gemini"


# ===========================================================================
# DIRECTORY INITIALIZATION — Happy Path
# ===========================================================================

class TestDirsHappy:
    # T-1.38
    def test_create_all_directories(self, tmp_path):
        data = {
            "vault_path": str(tmp_path / "vault"),
            "sources_path": str(tmp_path / "sources"),
        }
        cfg = load_config(str(_write_config(tmp_path, data)))
        ensure_directories(cfg)

        expected = [
            tmp_path / "vault" / "wiki" / "sources",
            tmp_path / "vault" / "wiki" / "entities",
            tmp_path / "vault" / "wiki" / "concepts",
            tmp_path / "vault" / "graph",
            tmp_path / "sources" / "articles",
            tmp_path / "sources" / "pdfs",
            tmp_path / "sources" / "notes",
        ]
        for d in expected:
            assert d.is_dir(), f"Missing directory: {d}"

    # T-1.39
    def test_idempotent_call_twice(self, tmp_path):
        data = {
            "vault_path": str(tmp_path / "vault"),
            "sources_path": str(tmp_path / "sources"),
        }
        cfg = load_config(str(_write_config(tmp_path, data)))
        ensure_directories(cfg)
        ensure_directories(cfg)

        assert (tmp_path / "vault" / "wiki" / "sources").is_dir()


# ===========================================================================
# DIRECTORY INITIALIZATION — Edge Cases
# ===========================================================================

class TestDirsEdge:
    # T-1.40
    def test_some_directories_already_exist(self, tmp_path):
        vault = tmp_path / "vault" / "wiki"
        vault.mkdir(parents=True)

        data = {
            "vault_path": str(tmp_path / "vault"),
            "sources_path": str(tmp_path / "sources"),
        }
        cfg = load_config(str(_write_config(tmp_path, data)))
        ensure_directories(cfg)

        assert (tmp_path / "vault" / "wiki" / "entities").is_dir()
        assert (tmp_path / "sources" / "articles").is_dir()

    # T-1.41
    def test_paths_with_spaces(self, tmp_path):
        data = {
            "vault_path": str(tmp_path / "my vault"),
            "sources_path": str(tmp_path / "my sources"),
        }
        cfg = load_config(str(_write_config(tmp_path, data)))
        ensure_directories(cfg)

        assert (tmp_path / "my vault" / "wiki" / "sources").is_dir()
        assert (tmp_path / "my sources" / "articles").is_dir()


# ===========================================================================
# DIRECTORY INITIALIZATION — Failure Cases
# ===========================================================================

class TestDirsFailure:
    # T-1.42
    def test_c8_violation_sources_inside_vault(self, tmp_path):
        data = {
            "vault_path": str(tmp_path / "vault"),
            "sources_path": str(tmp_path / "vault" / "sources"),
        }
        cfg = load_config(str(_write_config(tmp_path, data)))
        with pytest.raises(SystemExit) as exc_info:
            ensure_directories(cfg)
        assert "C-8" in _exit_msg(exc_info)

    # T-1.43
    def test_c8_violation_sources_equals_vault(self, tmp_path):
        same = str(tmp_path / "same")
        data = {
            "vault_path": same,
            "sources_path": same,
        }
        cfg = load_config(str(_write_config(tmp_path, data)))
        with pytest.raises(SystemExit) as exc_info:
            ensure_directories(cfg)
        msg = _exit_msg(exc_info)
        assert "C-8" in msg or "must not" in msg.lower()

    # T-1.44
    @pytest.mark.skipif(sys.platform == "win32", reason="chmod not reliable on Windows")
    def test_permission_error_propagated(self, tmp_path):
        ro = tmp_path / "readonly"
        ro.mkdir()
        ro.chmod(stat.S_IRUSR | stat.S_IXUSR)

        data = {
            "vault_path": str(ro / "vault"),
            "sources_path": str(tmp_path / "sources"),
        }
        cfg = load_config(str(_write_config(tmp_path, data)))
        try:
            with pytest.raises(OSError):
                ensure_directories(cfg)
        finally:
            ro.chmod(stat.S_IRWXU)
