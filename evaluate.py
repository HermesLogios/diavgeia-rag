import json
import statistics
import sys
import time
from collections import defaultdict

import agent
import ask


def run_rag(question):
    r = ask.answer(question)
    return {"answer": r["answer"] or "", "adas": r["retrieved_adas"],
            "invalid": r["invalid_citations"], "refused": r["refused"],
            "cost": r["cost"], "steps": 1}


def run_agent(question):
    r = agent.ask(question)
    text = (r["answer"] or "").strip()
    cited = sorted(set(ask.ADA_IN_TEXT.findall(text)))
    invalid = [a for a in cited if a not in r["adas"]]
    return {"answer": text, "adas": r["adas"], "invalid": invalid,
            "refused": r["refused"], "cost": r["cost"], "steps": r["steps"]}


PIPELINES = {"rag": run_rag, "agent": run_agent}


def evaluate(pipeline="rag", path="eval_set.json"):
    if pipeline not in PIPELINES:
        raise SystemExit(f"Άγνωστη διαδρομή '{pipeline}'. Χρήσε: rag ή agent.")

    with open(path, encoding="utf-8") as f:
        cases = json.load(f)

    run = PIPELINES[pipeline]
    print(f"Διαδρομή: {pipeline}  |  Warm-up...")
    try:
        run("δοκιμή")
    except Exception as exc:
        print(f"⚠ Το warm-up απέτυχε: {exc}")
    print(f"Τρέχω {len(cases)} περιπτώσεις...\n")

    results = []
    for case in cases:
        t0 = time.perf_counter()
        try:
            r = run(case["question"])
        except Exception as exc:
            r = {"answer": f"ΣΦΑΛΜΑ: {exc}", "adas": [], "invalid": [],
                 "refused": True, "cost": 0.0, "steps": 0}
        ms = (time.perf_counter() - t0) * 1000

        expected = case.get("expected_adas") or []
        found = [a for a in expected if a in r["adas"]]
        hit = None if not expected else (1.0 if found else 0.0)

        wanted = case.get("expected_contains") or []
        content_ok = None if not wanted else any(w in r["answer"] for w in wanted)

        citations_ok = not r["invalid"]
        refusal_ok = r["refused"] == case["should_refuse"]
        passed = (citations_ok and refusal_ok
                  and (hit is None or hit == 1.0)
                  and (content_ok is None or content_ok))

        results.append({
            "id": case["id"], "category": case["category"], "hit": hit,
            "content_ok": content_ok, "citations_ok": citations_ok,
            "refusal_ok": refusal_ok, "passed": passed, "ms": ms,
            "cost": r["cost"], "steps": r["steps"], "invalid": r["invalid"],
            "note": case.get("note", ""), "answer": r["answer"][:170],
        })

        h = " — " if hit is None else ("✅" if hit else "❌")
        c = " — " if content_ok is None else ("✅" if content_ok else "❌")
        print(f"  {'✅' if passed else '❌'} {case['id']:<12} {case['category']:<12} "
              f"ΑΔΑ {h}  τιμή {c}  παρ.{'✅' if citations_ok else '❌'} "
              f"αρν.{'✅' if refusal_ok else '❌'}  {r['steps']}β {ms:>6.0f} ms")

    print("\n" + "─" * 72)
    by_cat = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r["passed"])
    print("Ανά κατηγορία:")
    for cat, vals in sorted(by_cat.items()):
        print(f"  {cat:<14} {sum(vals)}/{len(vals)}")

    total = sum(r["passed"] for r in results)
    print(f"\nΣΥΝΟΛΟ    : {total}/{len(results)}  ({total / len(results):.0%})")
    print(f"Διάμεσος  : {statistics.median(r['ms'] for r in results):.0f} ms")
    print(f"Βήματα    : {sum(r['steps'] for r in results)} συνολικά")
    print(f"Κόστος    : ${sum(r['cost'] for r in results):.4f}")

    failures = [r for r in results if not r["passed"]]
    if failures:
        print(f"\n─── ΑΠΟΤΥΧΙΕΣ ({len(failures)}) ───")
        for r in failures:
            print(f"\n  ❌ {r['id']} ({r['category']})")
            if r["note"]:
                print(f"     {r['note']}")
            if r["invalid"]:
                print(f"     εφευρεθέντα ΑΔΑ: {r['invalid']}")
            print(f"     → {r['answer']}")

    out = f"eval_results_{pipeline}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nΑποθηκεύτηκε: {out}")


if __name__ == "__main__":
    evaluate(sys.argv[1] if len(sys.argv) > 1 else "rag")