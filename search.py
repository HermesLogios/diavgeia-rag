import os
import sys
import time

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

load_dotenv()

MODEL_NAME = "intfloat/multilingual-e5-base"

SQL = """
WITH candidates AS (
    SELECT c.ada, c.content, c.embedding <=> %s AS distance
    FROM chunks c
    WHERE c.embedding IS NOT NULL
    ORDER BY c.embedding <=> %s
    LIMIT 50
),
deduped AS (
    SELECT DISTINCT ON (content)
           content, ada, distance,
           count(*) OVER (PARTITION BY content) AS occurrences
    FROM candidates
    ORDER BY content, distance
)
SELECT d.ada, d.issue_date, d.expense_amount, dd.content,
       1 - dd.distance AS similarity, dd.occurrences
FROM deduped dd
JOIN decisions d ON d.ada = dd.ada
ORDER BY dd.distance
LIMIT 5;
"""

question = " ".join(sys.argv[1:]) or "προμήθεια ηλεκτρονικών υπολογιστών"
print(f"Ερώτηση: {question}\n")

model = SentenceTransformer(MODEL_NAME)
vec = model.encode(f"query: {question}", normalize_embeddings=True)

with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    register_vector(conn)
    with conn.cursor() as cur:
        t0 = time.time()
        cur.execute(SQL, (vec, vec))
        rows = cur.fetchall()
        ms = (time.time() - t0) * 1000

    for ada, issue_date, amount, content, sim, occ in rows:
        euro = f"{amount:,.2f}€" if amount else "—"
        rep = f"  (×{occ})" if occ > 1 else ""
        print(f"[{sim:.3f}] {issue_date} | {euro:>14} | {ada}{rep}")
        print(f"         {content[:110]}\n")

print(f"Χρόνος αναζήτησης: {ms:.0f} ms")