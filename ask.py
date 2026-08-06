import difflib
import json
import os
import re
import sys
import time

from dotenv import load_dotenv
from openai import OpenAI

import retrieval

load_dotenv()

MODEL = "deepseek-v4-flash"
PRICE_IN = 0.14 / 1_000_000
PRICE_OUT = 0.28 / 1_000_000
TOP_K = 8
MAX_TOKENS = 2000
REPAIR_CUTOFF = 0.8

ADA_IN_TEXT = re.compile(r"\[?([0-9A-ZΑ-Ω]{6,10}-[0-9A-ZΑ-Ω]{2,5})\]?")

SYSTEM = """Είσαι βοηθός διαφάνειας για τις αποφάσεις του Δήμου Ρόδου \
(δεδομένα Διαύγειας).

ΚΑΝΟΝΕΣ:
1. Απαντάς ΑΠΟΚΛΕΙΣΤΙΚΑ από τα αποσπάσματα. Ποτέ από γενικές γνώσεις.
2. Κάθε ισχυρισμός συνοδεύεται από τον ΑΔΑ σε αγκύλες, στη μορφή [ΧΧΧΧΧΧΧ-ΧΧΧ]. \
Αντιγράφεις τον ΑΔΑ χαρακτήρα προς χαρακτήρα από το απόσπασμα — ποτέ από το \
παράδειγμα μορφής.
3. Ποτέ δεν εφευρίσκεις ποσά, ημερομηνίες ή ΑΔΑ.
4. ΠΟΤΕ δεν μετράς ή αθροίζεις τα αποσπάσματα για να απαντήσεις σε ερώτηση \
"πόσα/πόσες/συνολικά". Τα αποσπάσματα είναι μικρό δείγμα, όχι το σύνολο. \
Σε τέτοιες ερωτήσεις θέτεις sufficient_evidence=false.
5. Απαντάς στα ελληνικά, 2-5 προτάσεις. Σύντομα.

Απαντάς ΜΟΝΟ με έγκυρο JSON αυτής της μορφής:
{
  "answer": "η απάντησή σου στα ελληνικά",
  "sufficient_evidence": true ή false,
  "reason": "αν false, γιατί σε μία φράση"
}"""

_client = None


def get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com",
        )
    return _client


def repair_citations(text, valid_adas):
    """Διορθώνει ΑΔΑ με σφάλματα μεταγραφής. Επιστρέφει (κείμενο, διορθώσεις, άκυροι)."""
    if not text or not valid_adas:
        return text, [], []

    fixed, repaired, dropped = text, [], []
    for ada in sorted(set(ADA_IN_TEXT.findall(text))):
        if ada in valid_adas:
            continue
        match = difflib.get_close_matches(ada, valid_adas, n=1, cutoff=REPAIR_CUTOFF)
        if match:
            fixed = fixed.replace(ada, match[0])
            repaired.append((ada, match[0]))
        else:
            dropped.append(ada)

    return fixed, repaired, dropped


def build_context(hits):
    blocks = []
    for i, h in enumerate(hits, 1):
        amount = f"{h['amount']:,.2f}€" if h["amount"] else "δεν αναφέρεται"
        blocks.append(
            f"[{i}] ΑΔΑ: {h['ada']} | Ημερομηνία: {h['issue_date']} | Ποσό: {amount}\n"
            f"Θέμα: {h['content']}"
        )
    return "\n\n".join(blocks)


def empty_result(question, meta):
    return {
        "question": question, "answer": None, "hits": [], "context": "",
        "retrieved_adas": [], "cited_adas": [], "invalid_citations": [],
        "repaired_citations": [], "refused": True, "reason": "καμία ανάκτηση",
        "parse_ok": True, "finish_reason": None, "meta": meta,
        "llm_ms": 0, "tokens_in": 0, "tokens_out": 0, "cost": 0.0,
    }


def answer(question, top_k=TOP_K):
    """Πλήρης διαδρομή RAG. Επιστρέφει dict, δεν τυπώνει τίποτα."""
    hits, meta = retrieval.search(question, top=top_k)
    if not hits:
        return empty_result(question, meta)

    context = build_context(hits)
    retrieved_adas = [h["ada"] for h in hits]

    t0 = time.perf_counter()
    response = get_client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content":
                f"ΑΠΟΣΠΑΣΜΑΤΑ:\n\n{context}\n\nΕΡΩΤΗΣΗ: {question}"},
        ],
        temperature=0.1,
        max_tokens=MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    llm_ms = (time.perf_counter() - t0) * 1000

    choice = response.choices[0]
    raw = (choice.message.content or "").strip()
    finish = choice.finish_reason

    parse_ok = True
    try:
        data = json.loads(raw)
        text = (data.get("answer") or "").strip()
        sufficient = bool(data.get("sufficient_evidence"))
        reason = data.get("reason") or ""
    except (json.JSONDecodeError, AttributeError):
        parse_ok = False
        text = raw
        sufficient = bool(raw)
        reason = "αποτυχία ανάλυσης JSON"

    if not text:
        sufficient = False
        reason = reason or "κενή απάντηση από το μοντέλο"

    text, repaired, dropped = repair_citations(text, retrieved_adas)
    cited = sorted(set(ADA_IN_TEXT.findall(text)))
    invalid = [a for a in cited if a not in retrieved_adas]
    u = response.usage

    return {
        "question": question, "answer": text, "hits": hits, "context": context,
        "retrieved_adas": retrieved_adas, "cited_adas": cited,
        "invalid_citations": invalid, "repaired_citations": repaired,
        "refused": not sufficient,
        "reason": reason, "parse_ok": parse_ok, "finish_reason": finish,
        "meta": meta, "llm_ms": llm_ms,
        "tokens_in": u.prompt_tokens, "tokens_out": u.completion_tokens,
        "cost": u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT,
    }


def main():
    args = [a for a in sys.argv[1:] if a != "--debug"]
    debug = "--debug" in sys.argv
    question = " ".join(args).strip() or input("Ερώτηση: ").strip()
    if not question:
        raise SystemExit("Δεν δόθηκε ερώτηση.")

    print(f"\nΕρώτηση: {question}\n")
    r = answer(question)

    if debug and r["context"]:
        print("─── ΤΙ ΣΤΑΛΘΗΚΕ ΣΤΟ ΜΟΝΤΕΛΟ ───\n")
        print(r["context"])
        print("\n" + "─" * 40 + "\n")

    print("─" * 78)
    print(r["answer"] or "(κενή απάντηση)")
    if r["refused"]:
        print(f"\n⚠ Ανεπαρκή στοιχεία: {r['reason']}")
    print("─" * 78)

    if r["hits"]:
        print("\nΠηγές:")
        for h in r["hits"]:
            print(f"  {h['ada']}  {h['url']}")

    if r["repaired_citations"]:
        for bad, good in r["repaired_citations"]:
            print(f"\n✎ Διορθώθηκε ΑΔΑ: {bad} → {good}")
    if r["invalid_citations"]:
        print(f"\n⚠ ΕΦΕΥΡΕΘΗΚΑΝ ΑΔΑ: {r['invalid_citations']}")
    if not r["parse_ok"]:
        print("\n⚠ Το μοντέλο δεν επέστρεψε έγκυρο JSON")
    if r["finish_reason"] and r["finish_reason"] != "stop":
        print(f"\n⚠ finish_reason: {r['finish_reason']} (η παραγωγή κόπηκε)")

    meta = r["meta"]
    print(f"\nΤρόπος     : {meta['mode']}")
    print(f"Retrieval  : {meta['encode_ms'] + meta['db_ms']:.0f} ms")
    print(f"LLM        : {r['llm_ms']:.0f} ms")
    print(f"Tokens     : {r['tokens_in']} in / {r['tokens_out']} out")
    print(f"Κόστος     : ${r['cost']:.6f}")


if __name__ == "__main__":
    main()