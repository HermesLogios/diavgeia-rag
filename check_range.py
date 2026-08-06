import requests

ADV = "https://diavgeia.gov.gr/luminapi/opendata/search/advanced.json"

RANGES = [
    ("2024 μόνο",      "2024-01-01", "2024-12-31"),
    ("2024 → 2025",    "2024-01-01", "2025-12-31"),
    ("2024 → σήμερα",  "2024-01-01", "2026-08-05"),
    ("2022 → σήμερα",  "2022-01-01", "2026-08-05"),
]

for label, start, end in RANGES:
    q = (f'organizationUid:"6265" AND '
         f"issueDate:[DT({start}T00:00:00) TO DT({end}T23:59:59)]")
    r = requests.get(ADV, params={"q": q, "size": 1}, timeout=60)

    if r.status_code != 200:
        print(f"{label:16} ✗ HTTP {r.status_code} — {r.text[:120]}\n")
        continue

    info = r.json().get("info", {})
    print(f"{label:16} total: {info.get('total'):>7,}")
    print(f"                 echo: {info.get('query')}\n")