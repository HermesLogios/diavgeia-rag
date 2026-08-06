import os, statistics, time
import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

load_dotenv()

QUERIES = [
    "προμήθεια καυσίμων για τα οχήματα του δήμου",
    "πρόσληψη εποχικού προσωπικού",
    "συντήρηση σχολικών κτιρίων",
    "δαπάνες τουριστικής προβολής",
    "αποκομιδή απορριμμάτων",
]

SQL = """
SELECT c.ada FROM chunks c
WHERE c.embedding IS NOT NULL
ORDER BY c.embedding <=> %s LIMIT 50;
"""

model = SentenceTransformer("intfloat/multilingual-e5-base")
vectors = [model.encode(f"query: {q}", normalize_embeddings=True) for q in QUERIES]

with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    register_vector(conn)
    with conn.cursor() as cur:
        for v in vectors:          # warm-up: δεν μετριέται
            cur.execute(SQL, (v,)); cur.fetchall()

        samples = []
        for _ in range(20):
            for v in vectors:
                t0 = time.perf_counter()
                cur.execute(SQL, (v,)); cur.fetchall()
                samples.append((time.perf_counter() - t0) * 1000)

samples.sort()
print(f"δείγματα : {len(samples)}")
print(f"διάμεσος : {statistics.median(samples):.1f} ms")
print(f"p95      : {samples[int(len(samples) * 0.95)]:.1f} ms")
print(f"max      : {max(samples):.1f} ms")