"""
model_cost_latency_comparison.py — runs the 6 fuzzy_vendor_match cases
through BOTH Ollama (qwen2.5:3b) and Haiku, measuring real latency,
real token usage, and real (tiny) dollar cost for Haiku.

This produces the actual cost/quality/latency evidence for the CTO
report — not estimated, measured directly.

Run with: python3 model_cost_latency_comparison.py
"""

import json
import time

import requests
from agent import llm_vendor_names_match

HAIKU_INPUT_RATE = 1.00 / 1_000_000   # $ per input token, Haiku 4.5, confirmed July 2026
HAIKU_OUTPUT_RATE = 5.00 / 1_000_000  # $ per output token

with open("fixture_100.json") as f:
    fixture = json.load(f)

fuzzy_cases = [b for b in fixture["bills"] if b["case_type"] == "fuzzy_vendor_match"]
purchase_orders = {p["po_id"]: p for p in fixture["purchase_orders"]}

# Reconstruct each fuzzy case's PO/Bill vendor pair by item match, same
# logic agent.py itself uses to find the fuzzy candidate.
pairs = []
for bill in fuzzy_cases:
    po_match = next(p for p in fixture["purchase_orders"] if p["item_name"] == bill["item_name"])
    pairs.append((po_match["vendor_name"], bill["vendor_name"]))

results = []

for po_vendor, bill_vendor in pairs:
    row = {"po_vendor": po_vendor, "bill_vendor": bill_vendor}

    # --- Ollama (qwen2.5:3b) ---
    start = time.time()
    try:
        prompt = (
            f'Are "{po_vendor}" and "{bill_vendor}" plausibly the same company '
            f'(e.g. abbreviations, legal suffixes like Ltd/Inc, minor spelling '
            f'differences)? Answer with exactly one word: yes or no.'
        )
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "qwen2.5:3b", "prompt": prompt, "stream": False},
            timeout=30,
        )
        answer = resp.json()["response"].strip().lower()
        first_word = answer.strip(".,!?").split()[0] if answer.strip() else ""
        row["ollama_answer"] = "yes" if first_word == "yes" else "no"
        row["ollama_latency_s"] = round(time.time() - start, 2)
        row["ollama_cost"] = 0.0  # local, no API charge
    except Exception as exc:
        row["ollama_answer"] = f"ERROR: {exc}"
        row["ollama_latency_s"] = round(time.time() - start, 2)
        row["ollama_cost"] = 0.0

    # --- Haiku ---
    start = time.time()
    try:
        import anthropic
        client = anthropic.Anthropic()
        prompt = (
            f'Are "{po_vendor}" and "{bill_vendor}" plausibly the same company '
            f'(e.g. abbreviations, legal suffixes like Ltd/Inc, minor spelling '
            f'differences)? Answer with exactly one word: yes or no.'
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = resp.content[0].text.strip().lower()
        first_word = answer.strip(".,!?").split()[0] if answer.strip() else ""
        row["haiku_answer"] = "yes" if first_word == "yes" else "no"
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

    results.append(row)

# --- Print comparison table ---
print(f"{'VENDOR PAIR':<50} {'OLLAMA':<8} {'LAT(s)':<8} {'HAIKU':<8} {'LAT(s)':<8} {'COST($)':<10}")
print("-" * 100)
total_ollama_latency = 0
total_haiku_latency = 0
total_haiku_cost = 0
for r in results:
    pair_label = f"{r['po_vendor'][:20]} vs {r['bill_vendor'][:20]}"
    print(f"{pair_label:<50} {r['ollama_answer']:<8} {r['ollama_latency_s']:<8} {r['haiku_answer']:<8} {r['haiku_latency_s']:<8} {r['haiku_cost']:<10}")
    total_ollama_latency += r["ollama_latency_s"]
    total_haiku_latency += r["haiku_latency_s"]
    total_haiku_cost += r["haiku_cost"]

print("-" * 100)
print(f"Total Ollama latency: {round(total_ollama_latency, 2)}s  |  Total Haiku latency: {round(total_haiku_latency, 2)}s")
print(f"Total Haiku cost for these {len(results)} calls: ${round(total_haiku_cost, 6)}")
print(f"Ollama cost: $0.00 (local, no API charge)")

with open("model_comparison_results.json", "w") as f:
    json.dump(results, f, indent=2)
print("\nFull results saved to model_comparison_results.json")
