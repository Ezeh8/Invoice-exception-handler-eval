"""
Runs the 6 fuzzy_vendor_match cases through BOTH Ollama (qwen2.5:3b) and
Haiku, measuring real latency, real token usage, and real (tiny) dollar
cost for Haiku.

This produces the actual cost/quality/latency evidence for the CTO
report — not estimated, measured directly.

Run from the project root: python3 -m scripts.compare_models
"""

import json
import time

from invoice_exception_handler.fixture_loading import REGRESSION_100_PATH, load_fixture
from invoice_exception_handler.vendor_matching import (
    answer_is_yes,
    ask_haiku,
    ask_ollama,
    build_vendor_match_prompt,
)

HAIKU_INPUT_RATE = 1.00 / 1_000_000   # $ per input token, Haiku 4.5, confirmed July 2026
HAIKU_OUTPUT_RATE = 5.00 / 1_000_000  # $ per output token
RESULTS_PATH = "model_comparison_results.json"


def main() -> None:
    results = [compare_pair(po_vendor, bill_vendor) for po_vendor, bill_vendor in fuzzy_vendor_pairs()]
    print_comparison_table(results)

    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results saved to {RESULTS_PATH}")


def fuzzy_vendor_pairs() -> list[tuple[str, str]]:
    """Reconstructs each fuzzy case's PO/Bill vendor pair by item match —
    the same way the matching engine finds its fuzzy candidate."""
    fixture = load_fixture(REGRESSION_100_PATH)
    fuzzy_cases = [b for b in fixture["bills"] if b["case_type"] == "fuzzy_vendor_match"]
    pairs = []
    for bill in fuzzy_cases:
        po_match = next(p for p in fixture["purchase_orders"] if p["item_name"] == bill["item_name"])
        pairs.append((po_match["vendor_name"], bill["vendor_name"]))
    return pairs


def compare_pair(po_vendor: str, bill_vendor: str) -> dict:
    prompt = build_vendor_match_prompt(po_vendor, bill_vendor)
    row = {"po_vendor": po_vendor, "bill_vendor": bill_vendor}

    start = time.time()
    try:
        row["ollama_answer"] = "yes" if answer_is_yes(ask_ollama(prompt)) else "no"
    except Exception as exc:
        row["ollama_answer"] = f"ERROR: {exc}"
    row["ollama_latency_s"] = round(time.time() - start, 2)
    row["ollama_cost"] = 0.0  # local, no API charge

    start = time.time()
    try:
        resp = ask_haiku(prompt)
        row["haiku_answer"] = "yes" if answer_is_yes(resp.content[0].text) else "no"
        row["haiku_latency_s"] = round(time.time() - start, 2)
        in_tok = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        row["haiku_input_tokens"] = in_tok
        row["haiku_output_tokens"] = out_tok
        row["haiku_cost"] = round(in_tok * HAIKU_INPUT_RATE + out_tok * HAIKU_OUTPUT_RATE, 8)
    except Exception as exc:
        row["haiku_answer"] = f"ERROR: {exc}"
        row["haiku_latency_s"] = round(time.time() - start, 2)
        row["haiku_cost"] = 0.0

    return row


def print_comparison_table(results: list[dict]) -> None:
    print(f"{'VENDOR PAIR':<50} {'OLLAMA':<8} {'LAT(s)':<8} {'HAIKU':<8} {'LAT(s)':<8} {'COST($)':<10}")
    print("-" * 100)
    for r in results:
        pair_label = f"{r['po_vendor'][:20]} vs {r['bill_vendor'][:20]}"
        print(f"{pair_label:<50} {r['ollama_answer']:<8} {r['ollama_latency_s']:<8} {r['haiku_answer']:<8} {r['haiku_latency_s']:<8} {r['haiku_cost']:<10}")

    total_ollama_latency = sum(r["ollama_latency_s"] for r in results)
    total_haiku_latency = sum(r["haiku_latency_s"] for r in results)
    total_haiku_cost = sum(r["haiku_cost"] for r in results)
    print("-" * 100)
    print(f"Total Ollama latency: {round(total_ollama_latency, 2)}s  |  Total Haiku latency: {round(total_haiku_latency, 2)}s")
    print(f"Total Haiku cost for these {len(results)} calls: ${round(total_haiku_cost, 6)}")
    print("Ollama cost: $0.00 (local, no API charge)")


if __name__ == "__main__":
    main()
