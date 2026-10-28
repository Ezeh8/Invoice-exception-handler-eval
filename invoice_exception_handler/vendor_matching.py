"""
Fuzzy vendor-name matching, used only when no PO matches the Bill's vendor
name exactly.

Two layers, cheapest first:
  1. Normalising the names (drop legal/generic suffixes, plurals, spacing,
     punctuation) settles cases like "Redwood Component Group" vs
     "Redwood Components" deterministically, with no LLM call.
  2. Otherwise, the ONE LLM-judgment case (D3) — kept in this module so
     it's the only place an LLM call happens. The LLM may answer "unsure",
     which the matching engine escalates to a human instead of guessing.
"""

import os
import re
from enum import Enum

import requests

HAIKU_MODEL = "claude-haiku-4-5-20251001"
OLLAMA_MODEL = "qwen2.5:3b"
OLLAMA_URL = "http://localhost:11434/api/generate"

# Words that say what kind of company it is, not which company it is.
LEGAL_AND_GENERIC_SUFFIXES = {
    "co", "company", "corp", "corporation", "group", "inc", "incorporated",
    "limited", "llc", "ltd", "plc",
}


class VendorMatchAnswer(str, Enum):
    YES = "yes"
    NO = "no"
    UNSURE = "unsure"


def names_match_after_normalising(name_a: str, name_b: str) -> bool:
    normalised_a = normalise_vendor_name(name_a)
    # An empty result (a name made only of suffixes) must never count as a match.
    return bool(normalised_a) and normalised_a == normalise_vendor_name(name_b)


def normalise_vendor_name(name: str) -> str:
    words = re.findall(r"[a-z0-9]+", name.lower())
    kept = [w for w in words if w not in LEGAL_AND_GENERIC_SUFFIXES]
    # Joined without spaces so "Blue Peak" and "Bluepeak" compare equal;
    # trailing "s" dropped so "Component" and "Components" do too.
    return "".join(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in kept)


def ask_llm_if_same_vendor(name_a: str, name_b: str, model: str = "haiku") -> VendorMatchAnswer:
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

    return parse_vendor_answer(answer)


def build_vendor_match_prompt(name_a: str, name_b: str) -> str:
    return (
        f'Are "{name_a}" and "{name_b}" the same company? Allow for '
        f'abbreviations, legal suffixes like Ltd/Inc, and minor spelling '
        f'differences. Answer with exactly one word: yes, no, or unsure. '
        f'Answer unsure only if you genuinely cannot tell.'
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


def parse_vendor_answer(answer: str) -> VendorMatchAnswer:
    # Take the first real word rather than a strict startswith — small
    # models often add filler ("Yes, they appear to be..."). Anything that
    # isn't a clear yes/no counts as unsure, so a garbled reply goes to a
    # human rather than being read as "no".
    words = answer.strip().lower().strip(".,!?").split()
    first_word = words[0].strip(".,!?") if words else ""
    try:
        return VendorMatchAnswer(first_word)
    except ValueError:
        return VendorMatchAnswer.UNSURE
