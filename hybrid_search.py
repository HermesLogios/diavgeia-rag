import os
import re
import sys
import time

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

load_dotenv()

MODEL_NAME = "intfloat/multilingual-e5-base"
CANDIDATES = 50   # πόσα φέρνει κάθε μέθοδος
K = 60            # σταθερά RRF
TOP = 5
AND_MIN = 5       # κάτω από τόσα AND-αποτελέσματα, πέφτουμε σε OR

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("Λείπει το DATABASE_URL. Τρέξε το script από τη ρίζα του project.")

# ΑΔΑ: 7 χαρακτήρες + παύλα + 3. Ελαστικό εύρος για ασφάλεια.
ADA_PATTERN = re.compile(r"^[0-9A-ZΑ-Ω]{6,10}-[0-9A-ZΑ-Ω]{2,5}$")

LOOKUP_SQL = """
SELECT ada, issue_date, expense_amount, subject, document_url
FROM decisions WHERE ada = %s;
"""

SQL = """
WITH q AS (
    SELECT
        plainto_tsquery('greek', immutable_unaccent(%(question)s)) AS tsq_and,
        NULLIF(replace(
            plainto_tsquery('greek', immutable_unaccent(%(question)s))::text,
            '&', '|'
        ), '')::tsquery AS tsq_or
),
and_count AS (
    SELECT count(*) AS n
    FROM chunks c, q
    WHERE q.tsq_and IS NOT NULL AND c.content_tsv @@ q.tsq_and
),
chosen AS (
    SELECT CASE WHEN (SELECT n FROM and_count) >= %(and_min)s
                THEN q.tsq_and ELSE q.tsq_or END AS tsq,
           (SELECT n FROM and_count) AS and_hits
    FROM q
),
dense AS (
    SELECT c.id, c.ada, c.content,
           ROW_NUMBER() OVER (ORDER BY c.embedding <=> %(vec)s) AS rank
    FROM chunks c
    WHERE c.embedding IS NOT NULL
    ORDER BY c.embedding <=> %(vec)s
    LIMIT %(cand)s
),
lexical AS (
    SELECT c.id, c.ada, c.content,
           ROW_NUMBER() OVER (ORDER BY ts_rank(c.content_tsv, ch.tsq, 1) DESC) AS rank
    FROM chunks c, chosen ch
    WHERE ch.tsq IS NOT NULL AND c.content_tsv @@ ch.tsq
    ORDER BY ts_rank(c.content_tsv, ch.tsq, 1) DESC
    LIMIT %(cand)s
),
fused AS (
    SELECT COALESCE(d.ada, l.ada) AS ada,
           COALESCE(d.content, l.content) AS content,
           COALESCE(1.0 / (%(k)s + d.rank), 0)
         + COALESCE(1.0 / (%(k)s + l.rank), 0) AS rrf,
           d.rank AS dense_rank,
           l.rank AS lex_rank
    FROM dense d
    FULL OUTER JOIN lexical l ON l.id = d.id
),
deduped AS (
    SELECT DISTINCT ON (content) *
    FROM fused
    ORDER BY content, rrf DESC
)
SELECT dd.ada, dec.issue_date, dec.expense_amount, dd.content,
       dd.rrf, dd.dense_rank, dd.lex_rank,
       (SELECT and_hits FROM chosen) AS and_hits
FROM deduped dd
JOIN decisions dec ON dec.ada = dd.ada
ORDER BY dd.rrf DESC
LIMIT %(top)s;
"""


def lookup_ada(ada):
    """Απευθείας αναζήτηση όταν η ερώτηση είναι ΑΔΑ — χωρίς μοντέλο, χωρίς διανύσματα."""
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        t0 = time.perf_counter()
        cur.execute(LOOKUP_SQL, (ada,))
        row = cur.fetchone()
        ms = (time.perf_counter() - t0) * 1000

    if not row:
        print("  Δεν βρέθηκε πράξη με αυτόν τον ΑΔΑ.")
    else:
        found_ada, issue_date, amount, subject, url = row
        euro = f"{amount:,.2f}€" if amount else "—"
        print(f"  ΑΔΑ   : {found_ada}")
        print(f"  Ημ/νία: {issue_date}")
        print(f"  Ποσό  : {euro}")
        print(f"  Θέμα  : {subject}")
        print(f"  PDF   : {url}")

    print(f"\nΧρόνος: {ms:.1f} ms")


def hybrid_search(question):
    """Dense + BM25, ενωμένα με Reciprocal Rank Fusion."""
    model = SentenceTransformer(MODEL_NAME)

    t_enc = time.perf_counter()
    vec = model.encode(f"query: {question}", normalize_embeddings=True)
    enc_ms = (time.perf_counter() - t_enc) * 1000

    with psycopg.connect(DATABASE_URL) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            t0 = time.perf_counter()
            cur.execute(SQL, {
                "question": question,
                "vec": vec,
                "cand": CANDIDATES,
                "k": K,
                "top": TOP,
                "and_min": AND_MIN,
            })
            rows = cur.fetchall()
            db_ms = (time.perf_counter() - t0) * 1000

    if not rows:
        print("  Κανένα αποτέλεσμα.")
        return

    and_hits = rows[0][7]
    mode = "AND (αυστηρό)" if and_hits >= AND_MIN else f"OR (εφεδρεία — AND έδωσε {and_hits})"
    print(f"Λεξιλογικός τρόπος: {mode}\n")

    print(f"{'RRF':>7}  {'dense':>5} {'bm25':>5}  {'ποσό':>13}  ΑΔΑ")
    print("─" * 78)

    for ada, issue_date, amount, content, rrf, d_rank, l_rank, _ in rows:
        euro = f"{amount:,.2f}€" if amount else "—"
        d = f"#{d_rank}" if d_rank else "—"
        l = f"#{l_rank}" if l_rank else "—"
        print(f"{rrf:.5f}  {d:>5} {l:>5}  {euro:>13}  {ada}  [{issue_date}]")
        print(f"          {content[:88]}\n")

    print(f"Encoding: {enc_ms:.1f} ms  |  Βάση: {db_ms:.1f} ms  |  Σύνολο: {enc_ms + db_ms:.1f} ms")


def main():
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        question = input("Ερώτηση: ").strip()

    if not question:
        raise SystemExit("Δεν δόθηκε ερώτηση.")

    print(f"\nΕρώτηση: {question}\n")

    if ADA_PATTERN.match(question.upper()):
        print("→ Αναγνωρίστηκε ΑΔΑ, απευθείας αναζήτηση στη βάση\n")
        lookup_ada(question.upper())
        return

    hybrid_search(question)


if __name__ == "__main__":
    main()