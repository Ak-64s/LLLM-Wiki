"""S-3 LLM Layer tests. Contract: contracts/s-3-llm-layer.contract.md"""

import sys
from dataclasses import dataclass
from unittest.mock import patch, MagicMock

import pytest
import requests

from src.core.chunking import chunk_text, get_threshold_chars, get_overlap_chars


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _exit_msg(exc_info) -> str:
    """Extract the error message from a SystemExit."""
    return str(exc_info.value.code) if exc_info.value.code is not None else ""


def _make_config(**overrides):
    """Build a Config with sensible defaults; override any field."""
    from src.core.config import Config
    defaults = {
        "vault_path": "vault",
        "sources_path": "sources",
        "default_provider": "gemini",
        "lmstudio_endpoint": "http://localhost:1234/v1",
        "gemini_model": "gemini-3-flash-preview",
        "chunk_threshold_lmstudio": 4000,
        "chunk_threshold_gemini": 750000,
        "chunk_overlap": 200,
        "graph_infer_confidence_threshold": 0.5,
    }
    defaults.update(overrides)
    return Config(**defaults)


def _gemini_ok_json(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _lmstudio_ok_json(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


# ===========================================================================
# CHUNKING — Happy Path
# ===========================================================================


class TestChunkingHappy:
    # T-3.01
    def test_text_under_threshold_returns_single_chunk(self):
        result = chunk_text("Hello", max_chars=100, overlap_chars=10)
        assert result == ["Hello"]

    # T-3.02
    def test_text_over_threshold_splits(self):
        text = "A" * 200
        result = chunk_text(text, max_chars=100, overlap_chars=20)
        assert len(result) == 3
        for chunk in result:
            assert len(chunk) <= 100

    # T-3.03
    def test_overlap_between_consecutive_chunks(self):
        text = "ABCDEFGHIJ" * 10  # 100 chars
        result = chunk_text(text, max_chars=50, overlap_chars=10)
        for i in range(len(result) - 1):
            overlap_region = result[i][-10:]
            next_start = result[i + 1][:10]
            assert overlap_region == next_start

    # T-3.04
    def test_last_chunk_may_be_shorter(self):
        text = "A" * 150
        result = chunk_text(text, max_chars=100, overlap_chars=0)
        assert result == ["A" * 100, "A" * 50]
        assert len(result[1]) == 50

    # T-3.05
    def test_get_threshold_chars_gemini(self):
        config = _make_config(chunk_threshold_gemini=750000)
        assert get_threshold_chars("gemini", config) == 3_000_000

    # T-3.06
    def test_get_threshold_chars_lmstudio(self):
        config = _make_config(chunk_threshold_lmstudio=4000)
        assert get_threshold_chars("lmstudio", config) == 16_000

    # T-3.07
    def test_get_overlap_chars(self):
        config = _make_config(chunk_overlap=200)
        assert get_overlap_chars(config) == 800


# ===========================================================================
# CHUNKING — Edge Cases
# ===========================================================================


class TestChunkingEdge:
    # T-3.08
    def test_text_exactly_at_threshold_no_split(self):
        text = "A" * 100
        result = chunk_text(text, max_chars=100, overlap_chars=10)
        assert result == ["A" * 100]

    # T-3.09
    def test_overlap_of_zero(self):
        text = "A" * 200
        result = chunk_text(text, max_chars=100, overlap_chars=0)
        assert result == ["A" * 100, "A" * 100]

    # T-3.10
    def test_single_character_text(self):
        result = chunk_text("X", max_chars=100, overlap_chars=10)
        assert result == ["X"]

    # T-3.11
    def test_overlap_almost_equals_max_chars(self):
        text = "A" * 200
        result = chunk_text(text, max_chars=100, overlap_chars=99)
        # Each chunk advances by 1 char, so many chunks
        assert len(result) > 100
        for chunk in result:
            assert len(chunk) <= 100


# ===========================================================================
# CHUNKING — Failure Cases
# ===========================================================================


class TestChunkingFailure:
    # T-3.12
    def test_max_chars_zero(self):
        with pytest.raises(ValueError):
            chunk_text("text", max_chars=0, overlap_chars=0)

    # T-3.13
    def test_max_chars_negative(self):
        with pytest.raises(ValueError):
            chunk_text("text", max_chars=-1, overlap_chars=0)

    # T-3.14
    def test_overlap_equals_max_chars(self):
        with pytest.raises(ValueError):
            chunk_text("text", max_chars=100, overlap_chars=100)

    # T-3.15
    def test_overlap_exceeds_max_chars(self):
        with pytest.raises(ValueError):
            chunk_text("text", max_chars=100, overlap_chars=200)

    # T-3.16
    def test_negative_overlap(self):
        with pytest.raises(ValueError):
            chunk_text("text", max_chars=100, overlap_chars=-1)


# ===========================================================================
# GEMINI COMPLETION — Happy Path
# ===========================================================================


class TestGeminiHappy:
    # T-3.17
    @patch("src.core.llm.requests.post")
    def test_gemini_returns_valid_response(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = _gemini_ok_json("Response text")
        mock_post.return_value = resp

        config = _make_config()
        env = {"GEMINI_API_KEY": "test-key"}
        result = complete("gemini", config, env, "system", "user content")
        assert result == "Response text"

    # T-3.18
    @patch("src.core.llm.requests.post")
    def test_gemini_strips_whitespace(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = _gemini_ok_json("  padded  ")
        mock_post.return_value = resp

        config = _make_config()
        env = {"GEMINI_API_KEY": "test-key"}
        result = complete("gemini", config, env, "system", "user content")
        assert result == "padded"

    # T-3.19
    @patch("src.core.llm._call_gemini")
    def test_complete_gemini_no_chunking(self, mock_call):
        from src.core.llm import complete
        mock_call.return_value = "short response"
        config = _make_config()
        env = {"GEMINI_API_KEY": "test-key"}
        result = complete("gemini", config, env, "system", "short input")
        assert result == "short response"


# ===========================================================================
# GEMINI COMPLETION — Edge Cases
# ===========================================================================


class TestGeminiEdge:
    # T-3.20
    @patch("src.core.llm.requests.post")
    def test_empty_system_prompt(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = _gemini_ok_json("response")
        mock_post.return_value = resp

        config = _make_config()
        env = {"GEMINI_API_KEY": "test-key"}
        result = complete("gemini", config, env, "", "user content")
        assert result == "response"

    # T-3.21
    @patch("src.core.llm._call_gemini")
    def test_multi_chunk_gemini(self, mock_call):
        from src.core.llm import complete
        mock_call.side_effect = ["Part 1", "Part 2"]
        config = _make_config(chunk_threshold_gemini=750000)
        # threshold_chars = 750000 * 4 = 3_000_000
        # user_content must exceed that
        long_content = "A" * 3_000_001
        env = {"GEMINI_API_KEY": "test-key"}
        result = complete("gemini", config, env, "system", long_content)
        assert "Part 1" in result
        assert "Part 2" in result
        assert "\n\n" in result


# ===========================================================================
# GEMINI COMPLETION — Failure Cases
# ===========================================================================


class TestGeminiFailure:
    # T-3.22
    @patch("src.core.llm.requests.post")
    def test_gemini_403_invalid_key(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 403
        mock_post.return_value = resp

        config = _make_config()
        env = {"GEMINI_API_KEY": "bad-key"}
        with pytest.raises(SystemExit) as exc_info:
            complete("gemini", config, env, "system", "content")
        msg = _exit_msg(exc_info)
        assert "403" in msg
        assert "API key" in msg

    # T-3.23
    @patch("src.core.llm.requests.post")
    def test_gemini_429_rate_limit(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 429
        mock_post.return_value = resp

        config = _make_config()
        env = {"GEMINI_API_KEY": "test-key"}
        with pytest.raises(SystemExit) as exc_info:
            complete("gemini", config, env, "system", "content")
        msg = _exit_msg(exc_info)
        assert "429" in msg
        assert "rate limit" in msg.lower()

    # T-3.24
    @patch("src.core.llm.requests.post")
    def test_gemini_500_server_error(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 500
        mock_post.return_value = resp

        config = _make_config()
        env = {"GEMINI_API_KEY": "test-key"}
        with pytest.raises(SystemExit) as exc_info:
            complete("gemini", config, env, "system", "content")
        msg = _exit_msg(exc_info)
        assert "500" in msg

    # T-3.25
    @patch("src.core.llm.requests.post")
    def test_gemini_connection_error(self, mock_post):
        from src.core.llm import complete
        mock_post.side_effect = requests.ConnectionError("refused")

        config = _make_config()
        env = {"GEMINI_API_KEY": "test-key"}
        with pytest.raises(SystemExit) as exc_info:
            complete("gemini", config, env, "system", "content")
        msg = _exit_msg(exc_info)
        assert "Cannot connect" in msg
        assert "Gemini" in msg

    # T-3.26
    @patch("src.core.llm.requests.post")
    def test_gemini_timeout(self, mock_post):
        from src.core.llm import complete
        mock_post.side_effect = requests.Timeout("timed out")

        config = _make_config()
        env = {"GEMINI_API_KEY": "test-key"}
        with pytest.raises(SystemExit) as exc_info:
            complete("gemini", config, env, "system", "content")
        msg = _exit_msg(exc_info)
        assert "timed out" in msg.lower()
        assert "Gemini" in msg

    # T-3.27
    @patch("src.core.llm.requests.post")
    def test_gemini_empty_response_text(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = _gemini_ok_json("")
        mock_post.return_value = resp

        config = _make_config()
        env = {"GEMINI_API_KEY": "test-key"}
        with pytest.raises(SystemExit) as exc_info:
            complete("gemini", config, env, "system", "content")
        msg = _exit_msg(exc_info)
        assert "empty response" in msg.lower()

    # T-3.28
    @patch("src.core.llm.requests.post")
    def test_gemini_malformed_json(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        mock_post.return_value = resp

        config = _make_config()
        env = {"GEMINI_API_KEY": "test-key"}
        with pytest.raises(SystemExit) as exc_info:
            complete("gemini", config, env, "system", "content")
        msg = _exit_msg(exc_info)
        assert "Gemini" in msg

    # T-3.29
    @patch("src.core.llm.requests.post")
    def test_gemini_json_missing_candidates(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {}
        mock_post.return_value = resp

        config = _make_config()
        env = {"GEMINI_API_KEY": "test-key"}
        with pytest.raises(SystemExit) as exc_info:
            complete("gemini", config, env, "system", "content")
        msg = _exit_msg(exc_info)
        assert "Gemini" in msg


# ===========================================================================
# LM STUDIO COMPLETION — Happy Path
# ===========================================================================


class TestLMStudioHappy:
    # T-3.30
    @patch("src.core.llm.requests.post")
    def test_lmstudio_returns_valid_response(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = _lmstudio_ok_json("LM response")
        mock_post.return_value = resp

        config = _make_config()
        env = {}
        result = complete("lmstudio", config, env, "system", "user content")
        assert result == "LM response"

    # T-3.31
    @patch("src.core.llm.requests.post")
    def test_lmstudio_strips_whitespace(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = _lmstudio_ok_json("  padded  ")
        mock_post.return_value = resp

        config = _make_config()
        env = {}
        result = complete("lmstudio", config, env, "system", "user content")
        assert result == "padded"

    # T-3.32
    @patch("src.core.llm._call_lmstudio")
    def test_complete_lmstudio_no_chunking(self, mock_call):
        from src.core.llm import complete
        mock_call.return_value = "short response"
        config = _make_config()
        env = {}
        result = complete("lmstudio", config, env, "system", "short input")
        assert result == "short response"


# ===========================================================================
# LM STUDIO COMPLETION — Edge Cases
# ===========================================================================


class TestLMStudioEdge:
    # T-3.33
    @patch("src.core.llm._call_lmstudio")
    def test_multi_chunk_lmstudio(self, mock_call):
        from src.core.llm import complete
        mock_call.side_effect = ["Part 1", "Part 2"]
        config = _make_config(chunk_threshold_lmstudio=4000)
        # threshold_chars = 4000 * 4 = 16000
        long_content = "A" * 16_001
        env = {}
        result = complete("lmstudio", config, env, "system", long_content)
        assert "Part 1" in result
        assert "Part 2" in result
        assert "\n\n" in result


# ===========================================================================
# LM STUDIO COMPLETION — Failure Cases
# ===========================================================================


class TestLMStudioFailure:
    # T-3.34
    @patch("src.core.llm.requests.post")
    def test_lmstudio_connection_refused(self, mock_post):
        from src.core.llm import complete
        mock_post.side_effect = requests.ConnectionError("refused")

        config = _make_config()
        env = {}
        with pytest.raises(SystemExit) as exc_info:
            complete("lmstudio", config, env, "system", "content")
        msg = _exit_msg(exc_info)
        assert "Cannot connect" in msg
        assert "LM Studio" in msg

    # T-3.35
    @patch("src.core.llm.requests.post")
    def test_lmstudio_timeout(self, mock_post):
        from src.core.llm import complete
        mock_post.side_effect = requests.Timeout("timed out")

        config = _make_config()
        env = {}
        with pytest.raises(SystemExit) as exc_info:
            complete("lmstudio", config, env, "system", "content")
        msg = _exit_msg(exc_info)
        assert "timed out" in msg.lower()
        assert "LM Studio" in msg

    # T-3.36
    @patch("src.core.llm.requests.post")
    def test_lmstudio_500(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 500
        mock_post.return_value = resp

        config = _make_config()
        env = {}
        with pytest.raises(SystemExit) as exc_info:
            complete("lmstudio", config, env, "system", "content")
        msg = _exit_msg(exc_info)
        assert "500" in msg

    # T-3.37
    @patch("src.core.llm.requests.post")
    def test_lmstudio_empty_response_text(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = _lmstudio_ok_json("")
        mock_post.return_value = resp

        config = _make_config()
        env = {}
        with pytest.raises(SystemExit) as exc_info:
            complete("lmstudio", config, env, "system", "content")
        msg = _exit_msg(exc_info)
        assert "empty response" in msg.lower()

    # T-3.38
    @patch("src.core.llm.requests.post")
    def test_lmstudio_malformed_json(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        mock_post.return_value = resp

        config = _make_config()
        env = {}
        with pytest.raises(SystemExit) as exc_info:
            complete("lmstudio", config, env, "system", "content")
        msg = _exit_msg(exc_info)
        assert "LM Studio" in msg

    # T-3.39
    @patch("src.core.llm.requests.post")
    def test_lmstudio_json_missing_choices(self, mock_post):
        from src.core.llm import complete
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {}
        mock_post.return_value = resp

        config = _make_config()
        env = {}
        with pytest.raises(SystemExit) as exc_info:
            complete("lmstudio", config, env, "system", "content")
        msg = _exit_msg(exc_info)
        assert "LM Studio" in msg


# ===========================================================================
# DISPATCH & VALIDATION — Happy Path
# ===========================================================================


class TestDispatchHappy:
    # T-3.40
    @patch("src.core.llm._call_gemini")
    def test_complete_dispatches_to_gemini(self, mock_call):
        from src.core.llm import complete
        mock_call.return_value = "gemini response"
        config = _make_config()
        env = {"GEMINI_API_KEY": "test-key"}
        result = complete("gemini", config, env, "system", "content")
        assert result == "gemini response"
        mock_call.assert_called_once()

    # T-3.41
    @patch("src.core.llm._call_lmstudio")
    def test_complete_dispatches_to_lmstudio(self, mock_call):
        from src.core.llm import complete
        mock_call.return_value = "lm response"
        config = _make_config()
        env = {}
        result = complete("lmstudio", config, env, "system", "content")
        assert result == "lm response"
        mock_call.assert_called_once()


# ===========================================================================
# DISPATCH & VALIDATION — Failure Cases
# ===========================================================================


class TestDispatchFailure:
    # T-3.42
    def test_invalid_provider_name(self):
        from src.core.llm import complete
        config = _make_config()
        with pytest.raises(SystemExit) as exc_info:
            complete("openai", config, {}, "system", "content")
        msg = _exit_msg(exc_info).lower()
        assert "openai" in msg
        assert "invalid provider" in msg

    # T-3.43
    def test_empty_user_content(self):
        from src.core.llm import complete
        config = _make_config()
        with pytest.raises(SystemExit) as exc_info:
            complete("gemini", config, {"GEMINI_API_KEY": "k"}, "system", "")
        msg = _exit_msg(exc_info).lower()
        assert "empty" in msg
