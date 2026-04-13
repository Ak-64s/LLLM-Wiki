"""Text chunking utilities. Contract: contracts/s-3-llm-layer.contract.md"""

_CHARS_PER_TOKEN = 4


def chunk_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    if max_chars <= 0:
        raise ValueError(f"max_chars must be > 0, got {max_chars}")
    if overlap_chars < 0:
        raise ValueError(f"overlap_chars must be >= 0, got {overlap_chars}")
    if overlap_chars >= max_chars:
        raise ValueError(
            f"overlap_chars ({overlap_chars}) must be < max_chars ({max_chars})"
        )

    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    step = max_chars - overlap_chars
    pos = 0
    while pos < len(text):
        chunks.append(text[pos : pos + max_chars])
        pos += step

    return chunks


def get_threshold_chars(provider: str, config) -> int:
    if provider == "lmstudio":
        return config.chunk_threshold_lmstudio * _CHARS_PER_TOKEN
    return config.chunk_threshold_gemini * _CHARS_PER_TOKEN


def get_overlap_chars(config) -> int:
    return config.chunk_overlap * _CHARS_PER_TOKEN
