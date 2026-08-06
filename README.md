# Διαφάνεια Ρόδου — Greek Public-Spending RAG Agent

Natural-language question answering over **36,739 public decisions** published by
the Municipality of Rhodes on Greece's transparency portal (Διαύγεια),
January 2023 – August 2026.

Ask in Greek, get a grounded answer with citations back to the original PDF.

```
"πόσα ξόδεψε ο δήμος για καύσιμα;"

  → aggregate(keyword="καύσιμα")
  → "8,358,476.65 € across 241 decisions. Only 138 carry a recorded
     amount, so this is a lower bound."

  4.9s · $0.0007
```

---

## What the data showed

| | |
|---|---|
| Decisions indexed | 36,739 |
| Recorded spending | **€423,583,932.81** |
| Decisions carrying an amount | 9,088 (**24.7%**) |
| Period | 2023-01-03 → 2026-08-05 |

Every total in this project is a **lower bound**: three quarters of decisions
have no amount field at all.

**School spending spiked 9× in 2025.** Roughly the same number of decisions
each year, but €18.3M against ~€2M in adjacent years. Asked *why*, the agent
chained five tool calls — yearly breakdown, then 2024-vs-2025 comparison, then
the largest items in each — and traced the entire anomaly to a single €15M
multi-year commitment for restoring the Academy school complex
[ΨΡΣ3Ω1Ρ-0ΙΞ].

| Year | Decisions | Spending |
|---|---|---|
| 2023 | 191 | €2,749,373 |
| 2024 | 148 | €2,076,532 |
| **2025** | 170 | **€18,326,728** |
| 2026 | 177 | €2,012,520 |

**The largest payees are not suppliers.** Waste management (€35.1M) and
electricity (€34.5M) dominate, followed by a bank and a loan fund — debt
service, not procurement. The tool is named `top_vendors` but its description
says *recipients of payments*, because the distinction matters.

---

## Architecture

```
INGESTION (once)                QUERY (per request)
────────────────                ───────────────────
Διαύγεια OpenData API           FastAPI  POST /ask
        │                               │
        ▼                               ▼
  Postgres 17                    ReAct agent loop
  + pgvector                            │
        │                    ┌──────────┴──────────┐
        ▼                    ▼                     ▼
  subject → chunk      hybrid retrieval        SQL tools
        │              HNSW dense + BM25    aggregate · top_by_amount
        ▼              fused with RRF       count_by_year · top_vendors
  multilingual-E5              │                     │
  768-dim vectors              └──────────┬──────────┘
        │                                 ▼
        ▼                          DeepSeek v4-flash
  HNSW + GIN index                        │
                                          ▼
                            answer + ΑΔΑ citations + cost
```

**Retrieval is hybrid.** Dense vectors (multilingual-E5-base, 768d, HNSW index)
are fused with Greek full-text search (snowball stemmer + `unaccent`, GIN index)
using Reciprocal Rank Fusion (k=60). Each method retrieves 50 candidates;
results are deduplicated by content and the top 5–8 are kept.

Both halves are load-bearing. Asked about school building maintenance, dense
retrieval misses a €99,050 payment because the subject is written in accounting
language — BM25 ranks it 4th. Asked *"what did the municipality buy for the
rubbish"*, BM25 finds nothing because the corpus says *απορρίμματα* and the
question says *σκουπίδια* — dense retrieval ranks it 1st.

**Aggregation questions bypass retrieval entirely.** "How much in total?" cannot
be answered from top-k documents at any k. The agent routes these to SQL.

**Bare ΑΔΑ lookups bypass everything.** A regex detects the identifier format
and queries Postgres directly — no embedding model, no LLM, ~15 ms.

---

## Results

Measured against a 17-case ground-truth set covering retrieval, paraphrase,
aggregation, entity lookup, spelling variation, and refusal traps.

| | RAG only | ReAct agent |
|---|---|---|
| **Overall** | 14/17 (82%) | **17/17 (100%)** |
| Aggregation | 0/3 | **3/3** |
| Retrieval | 6/6 | 6/6 |
| Hard cases | 2/2 | 2/2 |
| Refusal traps | 3/3 | 3/3 |
| Valid citations | 17/17 | 17/17 |
| **Cost** (17 questions) | **$0.0053** | $0.0171 |
| **Median latency** | **5.9s** | 7.1s |
| LLM calls | **17** | 36 |

**+18 points of accuracy for 3.2× the cost.** Simple retrieval questions do not
need the agent — a production deployment would route by question type rather
than sending everything through the expensive path.

### Metrics

Three checks, all deterministic, none requiring an LLM judge:

- **Hit@k** — is a known-correct ΑΔΑ among the retrieved documents?
- **Citation validity** — is every ΑΔΑ in the answer present in the retrieved
  set? Extracted by regex, compared against ground truth.
- **Refusal correctness** — the model declares `sufficient_evidence` as a
  structured field, so refusal is read, not guessed from phrasing.

---

## How it got there

The eval suite exists because it caught things that eyeballing never would.

| Score | What happened |
|---|---|
| 12/17 | RAG baseline |
| **10/17** | Adding the agent made it **worse**. Given the option not to call a tool, the model answered *"who is the mayor of Rhodes"* from training data in a single step — correct answer, plausible citation attached, zero grounding. Correct-looking hallucinations are more dangerous than obvious ones. |
| 15/17 | Programmatic guardrails: reject any reply with no tool call; reject `final_answer` with `sufficient_evidence=true` when no data tool has run. Enforced in the loop, not in the prompt, because the API rejects `tool_choice="required"`. |
| **regression** | A prompt rule added to fix one case (*"aggregate counts decisions, not people"*) over-generalised. A passing case started failing with a 5-step, 36-second refusal — the model no longer trusted `aggregate` at all. |
| **17/17** | Rule sharpened to distinguish the **unit asked for** from the **unit returned**. "How many decisions" and "how many employees" hit the same tool and must diverge. Both now pass. |

**Five of the early failures were wrong ground truth, not system bugs.** The
expected answers had been written by inspecting what the system returned — which
is circular, and guarantees a passing score that measures nothing. Ground truth
is now derived from SQL against the corpus.

---

## Findings worth documenting

### Greek-language retrieval

- Multilingual embeddings outperform Greek-specific encoders for retrieval
- The corpus contains both spellings **ΚΤΗΡΙΟ** and **ΚΤΙΡΙΟ**, which stem to
  different lexemes (`κτηρ` / `κτιρ`). Lexical search misses one; dense
  retrieval bridges the gap
- Greek capitals drop their accents, so `ΣΥΝΤΗΡΗΣΗ` and `Συντήρηση` produce
  different tokens. `unaccent` before `to_tsvector('greek', …)` is mandatory or
  half the corpus never matches
- `ILIKE` does **not** case-fold Greek under the container's default collation —
  a lowercase pattern silently misses text with capitals
- `plainto_tsquery` joins terms with `AND`. On conversational questions this
  returns nothing, so the system tries `AND` first and falls back to `OR` only
  when strict matching yields too few results

### Διαύγεια OpenData API

- The advanced search **silently caps any `issueDate` range to ~181 days**.
  Requesting a full year returns only the first half, with HTTP 200 and no
  warning. Discovered by comparing the requested range against the query the
  server echoes back. Ingestion runs in quarterly windows
- `/search.json` accepts `term`; `/search/advanced.json` accepts Lucene `q`.
  Sending `q` to the simple endpoint is ignored, not rejected
- `q` is both a parameter name and the full-text field name inside the index —
  `q:"πρόσληψη"` is valid syntax
- Dates must be wrapped as `DT(YYYY-MM-DDTHH:MM:SS)` or the query is rejected
- Results are sorted by recency over a live feed, so paginating a growing window
  yields duplicates. Fixed by pinning closed historical date ranges
- `extraFieldValues.org.name` is free text: 68% empty, inconsistent casing, and
  occasionally holds the vendor's name instead of the issuer's. Trust IDs

### LLM engineering

- Using a realistic identifier as a format example in a system prompt causes the
  model to emit it as a fabricated citation. Use `[ΧΧΧΧΧΧΧ-ΧΧΧ]`
- Citations are validated by regex against retrieved IDs. Near-misses caused by
  transcription errors (a dropped character) are repaired by fuzzy match at 0.8
  similarity rather than silently dropped
- `finish_reason` must be checked. Truncated JSON reads as a model failure when
  it is a `max_tokens` misconfiguration
- Where the time actually goes: making the vector index 125× faster
  (113 ms → 0.9 ms median) was irrelevant. Query encoding on CPU is 89% of
  retrieval latency, and the LLM is 95% of end-to-end latency
- Agentic loops cost roughly 3× a single call, because the full conversation is
  resent every turn

---

## Stack

Python 3.13 · FastAPI · PostgreSQL 17 + pgvector · sentence-transformers
(`intfloat/multilingual-e5-base`) · DeepSeek v4-flash · Docker Compose

Embeddings run locally on CPU: 36,739 texts in 38.5 minutes, zero marginal cost.
An API would have taken ~2 minutes and ~$0.02, but the pipeline is re-run often
during development, so local wins.

---

## Setup

```bash
git clone https://github.com/<username>/diavgeia-rag.git
cd diavgeia-rag

python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

copy .env.example .env                # add your DEEPSEEK_API_KEY

docker compose up -d
docker compose exec db psql -U rag -d diavgeia -c "CREATE EXTENSION IF NOT EXISTS vector;"
Get-Content schema.sql -Raw | docker compose exec -T db psql -U rag -d diavgeia
Get-Content migration_001_embeddings.sql -Raw | docker compose exec -T db psql -U rag -d diavgeia
Get-Content migration_002_hnsw.sql -Raw | docker compose exec -T db psql -U rag -d diavgeia
Get-Content migration_003_fts.sql -Raw | docker compose exec -T db psql -U rag -d diavgeia

python ingest.py                      # ~4 min   → 36,739 decisions
python embed.py                       # ~40 min on CPU
uvicorn api:app --port 8000
```

Then open http://127.0.0.1:8000/docs

```bash
python ask.py                         # RAG only, CLI
python agent.py                       # agent with tools, CLI
python evaluate.py rag                # run the eval suite
python evaluate.py agent
```

---

## Project structure

| File | Purpose |
|---|---|
| `ingest.py` | Fetches decisions from the Διαύγεια API in quarterly windows |
| `embed.py` | Generates 768-dim embeddings locally, resumable |
| `retrieval.py` | Hybrid search + RRF + ΑΔΑ routing. Returns data, prints nothing |
| `tools.py` | SQL aggregation tools exposed to the agent |
| `ask.py` | RAG pipeline: retrieve → prompt → structured JSON answer |
| `agent.py` | ReAct loop with function calling and grounding guardrails |
| `api.py` | FastAPI service with Pydantic contracts and CORS |
| `evaluate.py` | Runs the eval suite against either pipeline |
| `eval_set.json` | 17 ground-truth cases with notes on what each one probes |
| `schema.sql`, `migration_00*.sql` | Database schema and incremental migrations |

---

## Limitations

- Only decision **subjects** are indexed. The attached PDFs contain the actual
  text and are not yet parsed, so answers are limited to what a one-line title
  can convey
- 75% of decisions carry no amount, so every total is a lower bound
- The eval set now scores 100% and has **exhausted its discriminating power**.
  It caught a regression, an over-correction, and five bad ground-truth entries
  — but it needs new hard cases before it can catch the next one
- Single municipality. The pipeline generalises (5,417 organisations are
  available through the same API) but has not been run across them

---

## Next

PDF ingestion and chunking · cross-encoder reranking · cost-aware routing
between the RAG and agent paths · pytest + GitHub Actions CI · PWA frontend
