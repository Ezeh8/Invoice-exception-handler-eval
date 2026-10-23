"""
Fuzzy vendor-name matching — the ONE LLM-judgment case (D3).
Deliberately isolated in its own module so it's the only place an LLM
call happens; everything else in the matching flow is pure deterministic
logic.
"""

import os

import requests

HAIKU_MODEL = "claude-haiku-4-5-20251001"
OLLAMA_MODEL = "qwen2.5:3b"
OLLAMA_URL = "http://localhost:11434/api/generate"


def llm_vendor_names_match(name_a: str, name_b: str, model: str = "haiku") -> bool:
    """
    Real LLM call for fuzzy vendor-name matching (D3, D7).
    Default is "haiku" — qwen2.5:7b proved accurate but took ~12 minutes
    per call on this hardware (cold start), impractical for a pipeline.
    qwen2.5:3b is fast but got this exact case wrong. Haiku is fast AND
    correct, at a small per-call cost — the honest cost-quality tradeoff
    from D7, resolved in Haiku's favor for this specific judgment call.
    model="ollama" still available (uses local qwen2.5:3b) for testing
    the cost/quality difference side by side.
    """
    prompt = build_vendor_match_prompt(name_a, name_b)

    if model == "ollama":
        answer = ask_ollama(prompt)
    elif model == "haiku":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file before "
                "calling model='haiku'."
            )
        answer = ask_haiku(prompt).content[0].text
    else:
        raise ValueError(f"Unknown model: {model!r}. Use 'ollama' or 'haiku'.")

    return answer_is_yes(answer)


def build_vendor_match_prompt(name_a: str, name_b: str) -> str:
    return (
        f'Are "{name_a}" and "{name_b}" plausibly the same company '
        f'(e.g. abbreviations, legal suffixes like Ltd/Inc, minor spelling '
        f'differences)? Answer with exactly one word: yes or no.'
    )


def ask_ollama(prompt: str) -> str:
    resp = requests.post(
        OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["response"]


def ask_haiku(prompt: str):
    """Returns the full Anthropic response, not just the text, so
    scripts/compare_models.py can read token usage for its cost figures."""
    import anthropic

    client = anthropic.Anthropic()
    return client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=10,
        messages=[{"role": "user", "content": prompt}],
    )


def answer_is_yes(answer: str) -> bool:
    # Take the first real word rather than a strict startswith — small
    # models often add filler ("Yes, they appear to be...") that a plain
    # startswith would still catch, but "I think yes" would not.
    answer = answer.strip().lower()
    first_word = answer.strip(".,!?").split()[0] if answer.strip() else ""
    return first_word == "yes"
