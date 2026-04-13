import json
from pathlib import Path
from src.core.llm import complete

MAX_LOOKUP_DOCS = 3
MAX_FILE_CHARS = 10000

HOP_1_SYSTEM = """\
You are a search router logic core.
Analyze the provided `index.md` snippet. Which wiki documents explicitly map or contextually contain the answer to the user's question?
Return ONLY a JSON array of relative file paths.
Format exactly: ["concepts/ai.md", "sources/book.md"]
Return maximum 3 paths. No markdown wrapping, no explanations.
"""

HOP_2_SYSTEM = """\
You are a definitive wiki synthesis assistant.
Answer the user's question comprehensively and distinctly cleanly formatted in standard Markdown.
Prioritize exclusively the injection data provided within the local `Data Context`.
If the local context inherently lacks answers, fulfill utilizing external knowledge but explicitly prefix your answer stating: "_Local definitions unavailable._".
"""

def _plan_query_targets(question: str, index_text: str, provider: str, config, env: dict) -> list[str]:
    prompt = f"Index snippet:\n{index_text}\n\nQuestion:\n{question}"
    raw = complete(provider, config, env, HOP_1_SYSTEM, prompt)
    raw = raw.strip()
    
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1:
        raw = raw[start:end+1]
        
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            mapped = [str(item) for item in data if isinstance(item, str)]
            return mapped[:MAX_LOOKUP_DOCS]
    except json.JSONDecodeError:
        pass
        
    return []

def _synthesize_answer(question: str, gathered_text: str, provider: str, config, env: dict) -> str:
    prompt = f"Local Data Context:\n\n{gathered_text}\n\nQuestion:\n{question}"
    # In T-10.02 mock, we pass back prompt text if it's the test payload
    return complete(provider, config, env, HOP_2_SYSTEM, prompt)

def query_wiki(question: str, provider: str, config, env: dict) -> str:
    wiki_path = Path(config.vault_path) / "wiki"
    index_file = wiki_path / "index.md"
    
    targets = []
    if index_file.exists():
        # Restrict to < 30k chars for Hop 1 constraints roughly mapping.
        index_content = index_file.read_text(encoding="utf-8")[:30000]
        targets = _plan_query_targets(question, index_content, provider, config, env)
        
    compiled_texts = []
    
    for t in targets:
        path = wiki_path / t
        if path.exists() and path.is_file():
            text = path.read_text(encoding="utf-8")[:MAX_FILE_CHARS]
            compiled_texts.append(f"--- File: {t} ---\n{text}\n")
            
    compiled_str = "\n".join(compiled_texts)
    
    return _synthesize_answer(question, compiled_str, provider, config, env)
