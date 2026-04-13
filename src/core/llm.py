"""LLM completion interface. Contract: contracts/s-3-llm-layer.contract.md"""

import sys

import requests

from src.core.chunking import chunk_text, get_threshold_chars, get_overlap_chars

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_GEMINI_CONNECT_TIMEOUT = 30
_GEMINI_READ_TIMEOUT = 120
_LMSTUDIO_CONNECT_TIMEOUT = 30
_LMSTUDIO_READ_TIMEOUT = 300
_TEMPERATURE = 0.7


def _fail(msg: str) -> None:
    sys.exit(msg)


def complete(
    provider: str, config, env: dict, system_prompt: str, user_content: str
) -> str:
    if provider not in ("gemini", "lmstudio"):
        _fail(f"'{provider}' is an invalid provider. Use 'gemini' or 'lmstudio'.")

    if not user_content or not user_content.strip():
        _fail("user_content is empty. Nothing to send to the LLM.")

    threshold = get_threshold_chars(provider, config)
    overlap = get_overlap_chars(config)

    if len(user_content) > threshold:
        chunks = chunk_text(user_content, max_chars=threshold, overlap_chars=overlap)
        parts: list[str] = []
        for chunk in chunks:
            if provider == "gemini":
                parts.append(_call_gemini(config, env, system_prompt, chunk))
            else:
                parts.append(_call_lmstudio(config, system_prompt, chunk))
        return "\n\n".join(parts)

    if provider == "gemini":
        return _call_gemini(config, env, system_prompt, user_content)
    return _call_lmstudio(config, system_prompt, user_content)


def _call_gemini(config, env: dict, system_prompt: str, user_content: str) -> str:
    api_key = env.get("GEMINI_API_KEY", "")
    if not api_key:
        _fail("Missing GEMINI_API_KEY in environment.")

    url = (
        f"{_GEMINI_API_BASE}/models/{config.gemini_model}:generateContent"
        f"?key={api_key}"
    )
    payload = {
        "contents": [
            {"parts": [{"text": f"{system_prompt}\n\n{user_content}"}]}
        ]
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=(_GEMINI_CONNECT_TIMEOUT, _GEMINI_READ_TIMEOUT),
        )
    except requests.ConnectionError:
        _fail("Cannot connect to Gemini API.")
    except requests.Timeout:
        _fail("Gemini API request timed out.")

    if resp.status_code == 400:
        _fail("Gemini API error (400): bad request.")
    if resp.status_code == 403:
        _fail("Gemini API error (403): invalid API key. Check GEMINI_API_KEY in .env.")
    if resp.status_code == 429:
        _fail("Gemini API error (429): rate limit exceeded. Wait and retry.")
    if resp.status_code == 500:
        _fail("Gemini API error (500): server error.")
    if resp.status_code != 200:
        _fail(f"Gemini API error ({resp.status_code}): unexpected error.")

    try:
        data = resp.json()
    except (ValueError, TypeError):
        _fail("Gemini returned invalid JSON response.")

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        _fail("Gemini returned unexpected JSON structure.")

    text = text.strip()
    if not text:
        _fail("LLM returned empty response (gemini).")
    return text


def _call_lmstudio(config, system_prompt: str, user_content: str) -> str:
    endpoint = config.lmstudio_endpoint
    url = f"{endpoint}/chat/completions"
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": _TEMPERATURE,
        "max_tokens": -1,
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=(_LMSTUDIO_CONNECT_TIMEOUT, _LMSTUDIO_READ_TIMEOUT),
        )
    except requests.ConnectionError:
        _fail(f"Cannot connect to LM Studio at {endpoint}. Is it running?")
    except requests.Timeout:
        _fail("LM Studio request timed out.")

    if resp.status_code != 200:
        _fail(f"LM Studio API error ({resp.status_code}).")

    try:
        data = resp.json()
    except (ValueError, TypeError):
        _fail("LM Studio returned invalid JSON response.")

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        _fail("LM Studio returned unexpected JSON structure.")

    text = text.strip()
    if not text:
        _fail("LLM returned empty response (lmstudio).")
    return text
