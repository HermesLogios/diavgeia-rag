import requests

ADV = "https://diavgeia.gov.gr/luminapi/opendata/search/advanced.json"

ORGS = {
    "ΔΗΜΟΣ ΡΟΔΟΥ": "6265",
    "ΔΕΥΑΡ": "52826",
    "Δ.Ο.Π.Α.Ρ.": "53315",
    "ΡΟΔΑ": "53830",
    "Πρόνοια Δήμου Ρόδου": "50416",
}

YEARS = ["2022", "2023", "2024", "2025", "2026"]


def count(query):
    r = requests.get(ADV, params={"q": query, "size": 1}, timeout=60)
    if r.status_code != 200:
        return None
    return r.json().get("info", {}).get("total")


print("Ανά έτος — ΔΗΜΟΣ ΡΟΔΟΥ\n")
for y in YEARS:
    q = f'organizationUid:"6265" AND issueDate:[DT({y}-01-01T00:00:00) TO DT({y}-12-31T23:59:59)]'
    print(f"  {y}: {count(q):,}")

print("\nΑνά φορέα — 2024 έως σήμερα\n")
window = "issueDate:[DT(2024-01-01T00:00:00) TO DT(2026-08-05T23:59:59)]"
for name, uid in ORGS.items():
    total = count(f'organizationUid:"{uid}" AND {window}')
    print(f"  {name:24} {total:,}" if total is not None else f"  {name:24} ✗")