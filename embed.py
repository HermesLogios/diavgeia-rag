import os
import time

import numpy as np
import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("Λείπει το DATABASE_URL.")

MODEL_NAME = "intfloat/multilingual-e5-base"
FETCH_SIZE = 256      # πόσα τραβάμε από τη βάση κάθε φορά
ENCODE_BATCH = 32     # πόσα δίνουμε μαζί στο μοντέλο


def main():
    print(f"Φορτώνω το μοντέλο: {MODEL_NAME}")
    print("(την πρώτη φορά κατεβάζει ~1,1GB — υπομονή)\n")

    model = SentenceTransformer(MODEL_NAME)
    dim = model.get_sentence_embedding_dimension()
    print(f"Διαστάσεις μοντέλου: {dim}")

    if dim != 768:
        raise SystemExit(
            f"Το μοντέλο δίνει {dim} διαστάσεις αλλά η στήλη περιμένει 768."
        )

    started = time.time()
    done = 0

    with psycopg.connect(DATABASE_URL) as conn:
        register_vector(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM chunks WHERE embedding IS NULL")
            remaining = cur.fetchone()[0]

        print(f"Προς επεξεργασία: {remaining:,}\n")
        if not remaining:
            print("Τίποτα να κάνω.")
            return

        while True:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, content FROM chunks "
                    "WHERE embedding IS NULL ORDER BY id LIMIT %s",
                    (FETCH_SIZE,),
                )
                rows = cur.fetchall()

            if not rows:
                break

            ids = [r[0] for r in rows]
            texts = [f"passage: {r[1]}" for r in rows]

            vectors = model.encode(
                texts,
                batch_size=ENCODE_BATCH,
                normalize_embeddings=True,
                show_progress_bar=False,
            )

            with conn.cursor() as cur:
                cur.executemany(
                    "UPDATE chunks SET embedding = %s, model = %s WHERE id = %s",
                    [(np.asarray(v), MODEL_NAME, i) for v, i in zip(vectors, ids)],
                )
            conn.commit()

            done += len(rows)
            elapsed = time.time() - started
            rate = done / elapsed
            eta = (remaining - done) / rate / 60 if rate else 0
            print(f"  {done:>6,} / {remaining:,}  |  {rate:5.0f} κείμενα/δευτ  |  ETA {eta:4.1f} λεπτά")

    total = (time.time() - started) / 60
    print(f"\nΟλοκληρώθηκε σε {total:.1f} λεπτά.")


if __name__ == "__main__":
    main()