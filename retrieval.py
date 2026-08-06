import os
import re
import time

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

load_dotenv()

MODEL_NAME = "intfloat/multilingual-e5-base"
CANDIDATES = 50
K = 60
AND_MIN = 5

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("Λείπει το DATABASE_URL.")

ADA_PATTERN = re.compile(r"^[0-9A-ZΑ-Ω]{6,10}-[0-9A-ZΑ-Ω]{2,5}$")

_model = None


def get_model():
    """Φορτώνει το μοντέλο μία φορά και το ξαναχρησιμοποιεί."""
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


LOOKUP_SQL = """
SELECT ada, issue_date, expense_amount, subject, document_url
FROM decisions WHERE ada = %s;
"""

SEARCH_SQL = """
WITH q AS (
    SELECT
        plainto_tsquery('greek', immutable_unaccent(%(question)s)) AS tsq_and,
        NULLIF(replace(
            plainto_tsquery('greek', immutable_unaccent(%(question)s))::text,
            '&', '|'
        ), '')::tsquery AS tsq_or
),
and_count AS (
    SELECT count(*) AS n FROM chunks c, q
    WHERE q.tsq_and IS NOT NULL AND c.content_tsv @@ q.tsq_and
),
chosen AS (
    SELECT CASE WHEN (SELECT n FROM and_count) >= %(and_min)s
                THEN q.tsq_and ELSE q.tsq_or END AS tsq
    FROM q
),
dense AS (
    SELECT c.id, c.ada, c.content,
           ROW_NUMBER() OVER (ORDER BY c.embedding <=> %(vec)s) AS rank
    FROM chunks c WHERE c.embedding IS NOT NULL
    ORDER BY c.embedding <=> %(vec)s LIMIT %(cand)s
),
lexical AS (
    SELECT c.id, c.ada, c.content,
           ROW_NUMBER() OVER (ORDER BY ts_rank(c.content_tsv, ch.tsq, 1) DESC) AS rank
    FROM chunks c, chosen ch
    WHERE ch.tsq IS NOT NULL AND c.content_tsv @@ ch.tsq
    ORDER BY ts_rank(c.content_tsv, ch.tsq, 1) DESC LIMIT %(cand)s
),
fused AS (
    SELECT COALESCE(d.ada, l.ada) AS ada,
           COALESCE(d.content, l.content) AS content,
           COALESCE(1.0 / (%(k)s + d.rank), 0)
         + COALESCE(1.0 / (%(k)s + l.rank), 0) AS rrf,
           d.rank AS dense_rank, l.rank AS lex_rank
    FROM dense d FULL OUTER JOIN lexical l ON l.id = d.id
),
deduped AS (
    SELECT DISTINCT ON (content) * FROM fused ORDER BY content, rrf DESC
)
SELECT dd.ada, dec.issue_date, dec.expense_amount, dd.content,
       dec.document_url, dd.rrf, dd.dense_rank, dd.lex_rank
FROM deduped dd
JOIN decisions dec ON dec.ada = dd.ada
ORDER BY dd.rrf DESC LIMIT %(top)s;
"""


def lookup_ada(ada):
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(LOOKUP_SQL, (ada.upper(),))
        row = cur.fetchone()

    if not row:
        return []

    ada, issue_date, amount, subject, url = row
    return [{
        "ada": ada, "issue_date": issue_date, "amount": amount,
        "content": subject, "url": url,
        "rrf": None, "dense_rank": None, "lex_rank": None,
    }]


def search(question, top=8):
    """Επιστρέφει λίστα από dicts. Δεν τυπώνει τίποτα."""
    question = question.strip()

    if ADA_PATTERN.match(question.upper()):
        return lookup_ada(question), {"mode": "ada_lookup", "encode_ms": 0, "db_ms": 0}

    model = get_model()
    t0 = time.perf_counter()
    vec = model.encode(f"query: {question}", normalize_embeddings=True)
    encode_ms = (time.perf_counter() - t0) * 1000

    with psycopg.connect(DATABASE_URL) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            t1 = time.perf_counter()
            cur.execute(SEARCH_SQL, {
                "question": question, "vec": vec, "cand": CANDIDATES,
                "k": K, "top": top, "and_min": AND_MIN,
            })
            rows = cur.fetchall()
            db_ms = (time.perf_counter() - t1) * 1000

    hits = [{
        "ada": r[0], "issue_date": r[1], "amount": r[2], "content": r[3],
        "url": r[4], "rrf": r[5], "dense_rank": r[6], "lex_rank": r[7],
    } for r in rows]

    return hits, {"mode": "hybrid", "encode_ms": encode_ms, "db_ms": db_ms}