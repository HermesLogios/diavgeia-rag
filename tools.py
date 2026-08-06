import os
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("Λείπει το DATABASE_URL.")

# Κοινό φίλτρο: προαιρετική λέξη-κλειδί (με ελληνικό stemming) + προαιρετικό έτος.
# Το chunk_index = 0 μας προστατεύει όταν αργότερα προστεθούν chunks από PDF.
FILTER = """
FROM decisions d
JOIN chunks c ON c.ada = d.ada AND c.chunk_index = 0
WHERE (%(kw)s::text IS NULL
       OR c.content_tsv @@ plainto_tsquery('greek', immutable_unaccent(%(kw)s)))
  AND (%(year)s::int IS NULL
       OR date_part('year', d.issue_date) = %(year)s)
"""


def _run(sql, params):
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def aggregate(keyword=None, year=None):
    """Πλήθος και άθροισμα ποσών για αποφάσεις που ταιριάζουν."""
    sql = f"""
    SELECT count(*) AS plithos,
           count(d.expense_amount) AS me_poso,
           sum(d.expense_amount) AS synolo,
           round(avg(d.expense_amount), 2) AS mesos_oros,
           max(d.expense_amount) AS megisto,
           min(d.issue_date) AS apo,
           max(d.issue_date) AS eos
    {FILTER};
    """
    return _run(sql, {"kw": keyword, "year": year})[0]


def top_by_amount(keyword=None, year=None, limit=5):
    """Οι αποφάσεις με τα μεγαλύτερα ποσά που ταιριάζουν."""
    sql = f"""
    SELECT d.ada, d.issue_date, d.expense_amount, d.subject, d.document_url
    {FILTER}
      AND d.expense_amount IS NOT NULL
    ORDER BY d.expense_amount DESC
    LIMIT %(limit)s;
    """
    return _run(sql, {"kw": keyword, "year": year, "limit": limit})


def count_by_year(keyword=None):
    """Κατανομή αποφάσεων και δαπανών ανά έτος."""
    sql = f"""
    SELECT date_part('year', d.issue_date)::int AS etos,
           count(*) AS plithos,
           sum(d.expense_amount) AS synolo
    {FILTER}
    GROUP BY 1 ORDER BY 1;
    """
    return _run(sql, {"kw": keyword, "year": None})


def top_vendors(keyword=None, year=None, limit=5):
    """Οι μεγαλύτεροι αποδέκτες πληρωμών — από το raw JSONB."""
    sql = f"""
    SELECT d.raw->'extraFieldValues'->'sponsor'->0->'sponsorAFMName'->>'name'
               AS promitheftis,
           count(*) AS plithos,
           sum(d.expense_amount) AS synolo
    {FILTER}
      AND d.expense_amount IS NOT NULL
    GROUP BY 1
    HAVING d.raw->'extraFieldValues'->'sponsor'->0->'sponsorAFMName'->>'name' IS NOT NULL
    ORDER BY synolo DESC NULLS LAST
    LIMIT %(limit)s;
    """
    return _run(sql, {"kw": keyword, "year": year, "limit": limit})


def _demo():
    print("═══ aggregate(keyword='καύσιμα') ═══")
    for k, v in aggregate(keyword="καύσιμα").items():
        print(f"  {k:<12} {v}")

    print("\n═══ aggregate(year=2025) ═══")
    for k, v in aggregate(year=2025).items():
        print(f"  {k:<12} {v}")

    print("\n═══ top_by_amount(keyword='απορριμματοφόρα', limit=3) ═══")
    for r in top_by_amount(keyword="απορριμματοφόρα", limit=3):
        print(f"  {r['expense_amount']:>14,.2f}€  {r['ada']}  {r['subject'][:50]}")

    print("\n═══ count_by_year(keyword='σχολικών') ═══")
    for r in count_by_year(keyword="σχολικών"):
        total = f"{r['synolo']:,.0f}€" if r["synolo"] else "—"
        print(f"  {r['etos']}  {r['plithos']:>5}  {total:>16}")

    print("\n═══ top_vendors(limit=5) ═══")
    for r in top_vendors(limit=5):
        print(f"  {r['synolo']:>14,.2f}€  ({r['plithos']:>4})  {r['promitheftis'][:45]}")


if __name__ == "__main__":
    _demo()