import os
import json
import time
from datetime import date, datetime, timezone

import requests
import psycopg
from dotenv import load_dotenv

load_dotenv()

ADV = "https://diavgeia.gov.gr/luminapi/opendata/search/advanced.json"

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit(
        "Λείπει το DATABASE_URL. Έλεγξε ότι υπάρχει .env στη ρίζα του project "
        "και ότι τρέχεις το script από τον φάκελο diavgeia-rag."
    )

# ─── Ρυθμίσεις corpus ────────────────────────────────
ORG_UID = "6265"          # ΔΗΜΟΣ ΡΟΔΟΥ
START_YEAR = 2023
END_YEAR = 2026
PAGE_SIZE = 200
MAX_PAGES = 200
# Το API κόβει κάθε εύρος στις ~181 ημέρες — δουλεύουμε ανά τρίμηνο.
QUARTERS = [("01-01", "03-31"), ("04-01", "06-30"),
            ("07-01", "09-30"), ("10-01", "12-31")]
# ─────────────────────────────────────────────────────

TODAY = date.today().isoformat()


def windows():
    """Παράγει (αρχή, τέλος) για κάθε τρίμηνο, χωρίς να ξεπερνά το σήμερα."""
    for year in range(START_YEAR, END_YEAR + 1):
        for start_md, end_md in QUARTERS:
            start = f"{year}-{start_md}"
            end = f"{year}-{end_md}"
            if start > TODAY:
                return
            yield start, min(end, TODAY)


def build_query(start, end):
    return (
        f'organizationUid:"{ORG_UID}" AND '
        f"issueDate:[DT({start}T00:00:00) TO DT({end}T23:59:59)]"
    )


def fetch_page(query, page):
    params = {"q": query, "size": PAGE_SIZE, "page": page}
    r = requests.get(ADV, params=params, timeout=90)
    r.raise_for_status()
    return r.json()


def ms_to_date(ms):
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()


def parse(d):
    extra = d.get("extraFieldValues") or {}
    org = extra.get("org") or {}
    sponsors = extra.get("sponsor") or []

    total = 0.0
    currency = None
    for s in sponsors:
        amount_obj = s.get("expenseAmount") or {}
        amount = amount_obj.get("amount")
        if amount is not None:
            total += float(amount)
            currency = currency or amount_obj.get("currency")

    return {
        "ada": d.get("ada"),
        "subject": (d.get("subject") or "").strip(),
        "issue_date": ms_to_date(d.get("issueDate")),
        "organization_id": d.get("organizationId"),
        "organization_name": org.get("name"),
        "decision_type_id": d.get("decisionTypeId"),
        "expense_amount": total if sponsors else None,
        "currency": currency,
        "document_url": d.get("documentUrl"),
        "raw": json.dumps(d, ensure_ascii=False),
    }


UPSERT = """
INSERT INTO decisions (
    ada, subject, issue_date, organization_id, organization_name,
    decision_type_id, expense_amount, currency, document_url, raw
) VALUES (
    %(ada)s, %(subject)s, %(issue_date)s, %(organization_id)s, %(organization_name)s,
    %(decision_type_id)s, %(expense_amount)s, %(currency)s, %(document_url)s, %(raw)s
)
ON CONFLICT (ada) DO UPDATE SET
    subject = EXCLUDED.subject,
    raw = EXCLUDED.raw,
    fetched_at = now();
"""


def main():
    grand_total = 0
    started = time.time()

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        for start, end in windows():
            query = build_query(start, end)
            data = fetch_page(query, 0)
            info = data.get("info", {})
            available = info.get("total", 0)

            echo = str(info.get("query", ""))
            truncated = end[:10] not in echo

            flag = "  ⚠ ΚΟΠΗΚΕ" if truncated else ""
            print(f"\n{start} → {end} | {available:,} πράξεις{flag}")
            if truncated:
                print(f"   echo: {echo[:130]}")

            if not available:
                continue

            seen = 0
            for page in range(MAX_PAGES):
                if page > 0:
                    data = fetch_page(query, page)

                decisions = data.get("decisions") or []
                if not decisions:
                    break

                for d in decisions:
                    row = parse(d)
                    if not row["ada"] or not row["subject"]:
                        continue
                    cur.execute(UPSERT, row)
                    seen += 1

                conn.commit()
                print(f"   σελίδα {page:>2} | {seen:>5,} / {available:,}")

                if seen >= available:
                    break
                time.sleep(0.2)

            grand_total += seen

    elapsed = time.time() - started
    print(f"\nΣΥΝΟΛΟ: {grand_total:,} πράξεις σε {elapsed / 60:.1f} λεπτά.")


if __name__ == "__main__":
    main()