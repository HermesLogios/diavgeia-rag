import requests

BASE = "https://diavgeia.gov.gr/luminapi/opendata"
ADV = "/search/advanced.json"


def probe(label, path, params):
    params = {**params, "size": 1}
    try:
        r = requests.get(f"{BASE}{path}", params=params, timeout=60)
    except Exception as e:
        print(f"{label}\n   ✗ {e}\n")
        return

    if r.status_code != 200:
        print(f"{label}\n   ✗ HTTP {r.status_code} — {r.text[:150]}\n")
        return

    data = r.json()
    info = data.get("info", {})
    decisions = data.get("decisions") or []
    subject = (decisions[0].get("subject") or "") if decisions else "(κανένα)"
    total = info.get("total")

    print(f"{label}")
    print(f"   total: {total:,}" if isinstance(total, int) else f"   total: {total}")
    print(f"   εκτέλεσε: {str(info.get('query'))[:150]}")
    print(f"   δείγμα: {subject[:60]}\n")


probe("A. κείμενο ως πεδίο q", ADV, {"q": 'q:"πρόσληψη"'})
probe("B. φορέας + κείμενο",   ADV, {"q": 'organizationUid:"6209" AND q:"προμήθεια"'})
probe("C. ημερομηνία σκέτη",   ADV, {"q": 'q:"πρόσληψη" AND issueDate:[2026-01-01 TO 2026-06-30]'})
probe("D. ημερομηνία με DT()", ADV,
      {"q": 'q:"πρόσληψη" AND issueDate:[DT(2026-01-01T00:00:00) TO DT(2026-06-30T23:59:59)]'})
probe("E. τύπος πράξης",       ADV, {"q": 'decisionTypeUid:"Β.2.2"'})

print("=" * 60)
print("Αναζήτηση φορέα «Ρόδου» στη λίστα οργανισμών\n")

r = requests.get(f"{BASE}/organizations.json", timeout=180)
print(f"HTTP {r.status_code}")

if r.status_code == 200:
    payload = r.json()
    print("κλειδιά:", list(payload.keys()))
    orgs = payload.get("organizations") or []
    print(f"σύνολο φορέων: {len(orgs)}\n")
    for o in orgs:
        label = (o.get("label") or "").upper()
        if "ΡΟΔ" in label:
            print(f"  uid={o.get('uid')}  |  {o.get('label')}")