import json
import os
import sys
import time
from datetime import date, datetime
from decimal import Decimal

from dotenv import load_dotenv
from openai import OpenAI

import retrieval
import tools
from ask import repair_citations

load_dotenv()

MODEL = "deepseek-v4-flash"
PRICE_IN = 0.14 / 1_000_000
PRICE_OUT = 0.28 / 1_000_000
MAX_STEPS = 6
MAX_NUDGES = 2

SYSTEM = """Είσαι βοηθός διαφάνειας για τις αποφάσεις του Δήμου Ρόδου \
(δεδομένα Διαύγειας 2023-2026, 36.739 πράξεις του φορέα uid 6265).

ΑΠΟΛΥΤΟΣ ΚΑΝΟΝΑΣ:
Δεν γνωρίζεις ΤΙΠΟΤΑ για τη Ρόδο, τον δήμο, πρόσωπα ή γεγονότα πέρα από \
όσα επιστρέφουν τα εργαλεία. Η εκπαίδευσή σου ΔΕΝ είναι πηγή. Αν κάτι δεν \
προκύπτει από αποτέλεσμα εργαλείου, δεν το γράφεις — ούτε ως "γενική \
γνώση", ούτε ως συμπλήρωμα, ούτε ως υποσημείωση.

ΕΠΙΛΟΓΗ ΕΡΓΑΛΕΙΟΥ:
- "τι/ποιες/ποιος" για συγκεκριμένες αποφάσεις ή πρόσωπα → search_decisions
- "πόσα/πόσες/συνολικά" → aggregate
- "ποια είχε το μεγαλύτερο ποσό" → top_by_amount
- "ανά έτος / εξέλιξη" → count_by_year
- "ποιος πληρώθηκε περισσότερα" → top_vendors

ΠΡΩΤΗ ΑΝΑΖΗΤΗΣΗ:
Στην πρώτη κλήση του search_decisions περνάς την ερώτηση του χρήστη ΑΥΤΟΥΣΙΑ. \
Το εργαλείο χειρίζεται ήδη συνώνυμα και παραφράσεις. Αναδιατύπωση μόνο αν η \
πρώτη κλήση δεν φέρει σχετικά αποτελέσματα.

ΜΟΝΑΔΑ ΜΕΤΡΗΣΗΣ:
Το aggregate επιστρέφει plithos = αριθμός ΑΠΟΦΑΣΕΩΝ.
- Αν η ερώτηση ζητάει αριθμό αποφάσεων ή πράξεων ("πόσες αποφάσεις εξέδωσε", \
"πόσες πράξεις", "πόσες δαπάνες καταγράφηκαν"), τότε το plithos ΕΙΝΑΙ η \
απάντηση. Την δίνεις κανονικά με sufficient_evidence=true. Μία κλήση αρκεί.
- Αν η ερώτηση ζητάει ΔΙΑΦΟΡΕΤΙΚΗ μονάδα (πόσους υπαλλήλους, πόσα οχήματα, \
πόσα σχολεία, πόσους κατοίκους), το plithos ΔΕΝ είναι η απάντηση, γιατί μία \
απόφαση δεν ισούται με ένα άτομο ή αντικείμενο. Τότε sufficient_evidence=false.

ΤΕΛΙΚΗ ΑΠΑΝΤΗΣΗ:
Τελειώνεις ΠΑΝΤΑ καλώντας final_answer. Θέτεις sufficient_evidence=false \
όταν: τα εργαλεία δεν έδωσαν σχετικά δεδομένα, η ερώτηση αφορά κάτι εκτός \
των αποφάσεων του Δήμου Ρόδου, ή η ζητούμενη μονάδα δεν είναι αυτή που \
επιστρέφουν τα εργαλεία. Τότε το answer λέει ΜΟΝΟ τι δεν μπορείς να \
απαντήσεις — καμία εναλλακτική πληροφορία.

ΜΟΡΦΗ:
Ελληνικά, 2-5 προτάσεις. Κάθε συγκεκριμένη απόφαση με τον ΑΔΑ σε αγκύλες, \
στη μορφή [ΧΧΧΧΧΧΧ-ΧΧΧ]. Αντιγράφεις τον ΑΔΑ χαρακτήρα προς χαρακτήρα από το \
αποτέλεσμα του εργαλείου — ποτέ από το παράδειγμα μορφής. Αν me_poso < \
plithos, ανάφερε ότι το άθροισμα είναι κάτω όριο."""

SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_decisions",
            "description": "Σημασιολογική + λεξιλογική αναζήτηση στα θέματα των "
                           "αποφάσεων. Για 'τι/ποιες αποφάσεις αφορούν Χ' και για "
                           "αναζήτηση προσώπων ή φορέων μέσα στα θέματα. "
                           "ΠΡΩΤΗ ΚΛΗΣΗ: χρησιμοποίησε την ερώτηση του χρήστη "
                           "ΑΥΤΟΥΣΙΑ, χωρίς αναδιατύπωση. Μόνο αν δεν φέρει "
                           "σχετικά αποτελέσματα, δοκίμασε άλλες διατυπώσεις.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Το θέμα αναζήτησης"},
                    "top": {"type": "integer", "description": "Πλήθος (προεπιλογή 8)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate",
            "description": "Επιστρέφει plithos (αριθμός αποφάσεων που ταιριάζουν), "
                           "me_poso (πόσες έχουν καταγεγραμμένο ποσό), synolo "
                           "(άθροισμα ποσών), mesos_oros, megisto, apo, eos. "
                           "Χρησιμοποίησέ το για κάθε ερώτηση 'πόσες αποφάσεις' ή "
                           "'πόσα ξοδεύτηκαν'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string",
                                "description": "π.χ. 'καύσιμα'. Παράλειψέ το για "
                                               "όλες τις αποφάσεις."},
                    "year": {"type": "integer", "description": "π.χ. 2025"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "top_by_amount",
            "description": "Οι αποφάσεις με τα μεγαλύτερα ποσά.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "year": {"type": "integer"},
                    "limit": {"type": "integer", "description": "Προεπιλογή 5"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_by_year",
            "description": "Κατανομή πλήθους αποφάσεων και δαπανών ανά έτος.",
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "top_vendors",
            "description": "Οι μεγαλύτεροι ΑΠΟΔΕΚΤΕΣ ΠΛΗΡΩΜΩΝ. Περιλαμβάνει και "
                           "τράπεζες, ΔΟΥ και ταμεία δανείων — δεν είναι όλοι "
                           "προμηθευτές.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "year": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "final_answer",
            "description": "Δίνει την τελική απάντηση και τερματίζει. "
                           "Καλείται ΠΑΝΤΑ στο τέλος.",
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {"type": "string",
                               "description": "Η απάντηση στα ελληνικά"},
                    "sufficient_evidence": {
                        "type": "boolean",
                        "description": "false αν τα εργαλεία δεν έδωσαν επαρκή "
                                       "σχετικά δεδομένα ή η ερώτηση είναι εκτός "
                                       "πεδίου"},
                    "reason": {"type": "string",
                               "description": "Αν false, γιατί σε μία φράση"},
                },
                "required": ["answer", "sufficient_evidence"],
            },
        },
    },
]

NUDGE_NO_TOOL = (
    "ΣΦΑΛΜΑ: δεν κάλεσες εργαλείο. Δεν επιτρέπεται να απαντήσεις από δική σου "
    "γνώση. Κάλεσε πρώτα ένα εργαλείο δεδομένων και μετά final_answer."
)

NUDGE_NO_DATA = (
    "ΣΦΑΛΜΑ: δήλωσες sufficient_evidence=true χωρίς να έχεις καλέσει κανένα "
    "εργαλείο δεδομένων. Είτε κάλεσε εργαλείο για να τεκμηριώσεις την απάντηση, "
    "είτε ξανακάλεσε final_answer με sufficient_evidence=false."
)


def _search_decisions(query, top=8):
    hits, _ = retrieval.search(query, top=top)
    return [{"ada": h["ada"], "issue_date": h["issue_date"],
             "expense_amount": h["amount"], "subject": h["content"]} for h in hits]


REGISTRY = {
    "search_decisions": _search_decisions,
    "aggregate": tools.aggregate,
    "top_by_amount": tools.top_by_amount,
    "count_by_year": tools.count_by_year,
    "top_vendors": tools.top_vendors,
}


def _default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)


_client = None


def get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                         base_url="https://api.deepseek.com")
    return _client


def _result(answer, refused, reason, trace, adas, steps, started, t_in, t_out,
            repaired=None):
    return {"answer": answer, "refused": refused, "reason": reason,
            "trace": trace, "adas": sorted(set(adas)), "steps": steps,
            "repaired_citations": repaired or [],
            "ms": (time.perf_counter() - started) * 1000,
            "tokens_in": t_in, "tokens_out": t_out,
            "cost": t_in * PRICE_IN + t_out * PRICE_OUT}


def ask(question, verbose=False):
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": question},
    ]
    trace, adas = [], []
    t_in = t_out = 0
    nudges = 0
    started = time.perf_counter()

    for step in range(MAX_STEPS):
        r = get_client().chat.completions.create(
            model=MODEL, messages=messages, tools=SCHEMA,
            tool_choice="auto", temperature=0.1, max_tokens=2000,
        )
        t_in += r.usage.prompt_tokens
        t_out += r.usage.completion_tokens

        msg = r.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        # Απάντησε χωρίς να καλέσει εργαλείο — δεν το δεχόμαστε
        if not msg.tool_calls:
            nudges += 1
            if nudges > MAX_NUDGES:
                return _result(
                    "Δεν μπόρεσα να τεκμηριώσω απάντηση από τα δεδομένα.",
                    True, "το μοντέλο αρνήθηκε να χρησιμοποιήσει εργαλεία",
                    trace, adas, step + 1, started, t_in, t_out)
            if verbose:
                print("  ⚠ απάντηση χωρίς εργαλείο — επαναφορά")
            messages.append({"role": "user", "content": NUDGE_NO_TOOL})
            continue

        # Πρώτα τα εργαλεία δεδομένων, το final_answer τελευταίο
        final_call = None
        for call in msg.tool_calls:
            name = call.function.name

            if name == "final_answer":
                final_call = call
                continue

            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if verbose:
                shown = ", ".join(f"{k}={v!r}" for k, v in args.items())
                print(f"  → {name}({shown[:90]})")

            try:
                result = REGISTRY[name](**args)
            except Exception as exc:
                result = {"error": str(exc)}

            trace.append({"tool": name, "args": args})
            if isinstance(result, list):
                adas += [row["ada"] for row in result
                         if isinstance(row, dict) and "ada" in row]

            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(result, ensure_ascii=False,
                                                   default=_default)})

        if final_call is None:
            continue

        try:
            args = json.loads(final_call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}

        text = (args.get("answer") or "").strip()
        sufficient = bool(args.get("sufficient_evidence"))

        if verbose:
            print(f"  → final_answer(sufficient_evidence={sufficient})")

        # Ισχυρίζεται επάρκεια χωρίς να έχει κοιτάξει δεδομένα
        if sufficient and not trace and nudges < MAX_NUDGES:
            nudges += 1
            if verbose:
                print("  ⚠ επάρκεια χωρίς δεδομένα — επαναφορά")
            messages.append({"role": "tool", "tool_call_id": final_call.id,
                             "content": NUDGE_NO_DATA})
            continue

        # Διόρθωση ΑΔΑ με σφάλματα μεταγραφής
        text, repaired, _dropped = repair_citations(text, sorted(set(adas)))
        if verbose and repaired:
            for bad, good in repaired:
                print(f"  ✎ διορθώθηκε ΑΔΑ: {bad} → {good}")

        return _result(text, not sufficient or not text,
                       args.get("reason") or "", trace, adas,
                       step + 1, started, t_in, t_out, repaired)

    return _result("Δεν κατέληξα σε απάντηση εντός των επιτρεπτών βημάτων.",
                   True, "εξάντληση βημάτων", trace, adas, MAX_STEPS,
                   started, t_in, t_out)


def main():
    args = [a for a in sys.argv[1:] if a != "--quiet"]
    verbose = "--quiet" not in sys.argv
    question = " ".join(args).strip() or input("Ερώτηση: ").strip()
    if not question:
        raise SystemExit("Δεν δόθηκε ερώτηση.")

    print(f"\nΕρώτηση: {question}\n")
    if verbose:
        print("Εργαλεία:")

    r = ask(question, verbose=verbose)

    print("\n" + "─" * 78)
    print(r["answer"])
    if r["refused"] and r["reason"]:
        print(f"\n⚠ Ανεπαρκή στοιχεία: {r['reason']}")
    print("─" * 78)

    if r["adas"]:
        print("\nΠηγές:")
        for a in r["adas"][:10]:
            print(f"  {a}  https://diavgeia.gov.gr/doc/{a}")

    if r["repaired_citations"]:
        for bad, good in r["repaired_citations"]:
            print(f"\n✎ Διορθώθηκε ΑΔΑ: {bad} → {good}")

    print(f"\nΒήματα  : {r['steps']}")
    print(f"Χρόνος  : {r['ms']:.0f} ms")
    print(f"Tokens  : {r['tokens_in']} in / {r['tokens_out']} out")
    print(f"Κόστος  : ${r['cost']:.6f}")


if __name__ == "__main__":
    main()