import time
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import agent
import ask
import retrieval
import tools

DIAVGEIA_DOC = "https://diavgeia.gov.gr/doc/"


# ─── Μοντέλα εισόδου/εξόδου ──────────────────────────

class AskRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=500,
                          description="Η ερώτηση στα ελληνικά")
    mode: Literal["agent", "rag"] = Field(
        "agent", description="agent = με εργαλεία SQL, rag = μόνο ανάκτηση")


class Source(BaseModel):
    ada: str
    url: str
    issue_date: Optional[str] = None
    expense_amount: Optional[float] = None
    subject: Optional[str] = None


class ToolCall(BaseModel):
    tool: str
    args: dict


class AskResponse(BaseModel):
    question: str
    answer: str
    sufficient_evidence: bool
    reason: str = ""
    sources: list[Source] = []
    tool_calls: list[ToolCall] = []
    steps: int
    latency_ms: float
    tokens_in: int
    tokens_out: int
    cost_usd: float


class StatsResponse(BaseModel):
    total_decisions: int
    with_amount: int
    total_amount: float
    first_date: str
    last_date: str
    organization: str = "ΔΗΜΟΣ ΡΟΔΟΥ"


# ─── Εκκίνηση ────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Φόρτωση μοντέλου embeddings...")
    t0 = time.perf_counter()
    retrieval.get_model()
    print(f"Έτοιμο σε {time.perf_counter() - t0:.1f} δευτ.")
    yield
    print("Τερματισμός.")


app = FastAPI(
    title="Διαφάνεια Ρόδου",
    description="Ερωτήσεις σε φυσική γλώσσα πάνω στις αποφάσεις "
                "του Δήμου Ρόδου (Διαύγεια 2023-2026).",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ─── Endpoints ───────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": retrieval._model is not None}


@app.get("/stats", response_model=StatsResponse)
def stats():
    try:
        agg = tools.aggregate()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Η βάση δεν απαντά: {exc}")

    return StatsResponse(
        total_decisions=agg["plithos"],
        with_amount=agg["me_poso"],
        total_amount=float(agg["synolo"] or 0),
        first_date=str(agg["apo"]),
        last_date=str(agg["eos"]),
    )


@app.post("/ask", response_model=AskResponse)
def ask_endpoint(req: AskRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Κενή ερώτηση.")

    try:
        if req.mode == "agent":
            r = agent.ask(question)
            sources = [Source(ada=a, url=DIAVGEIA_DOC + a) for a in r["adas"]]
            tool_calls = [ToolCall(**t) for t in r["trace"]]
            return AskResponse(
                question=question,
                answer=r["answer"],
                sufficient_evidence=not r["refused"],
                reason=r["reason"],
                sources=sources,
                tool_calls=tool_calls,
                steps=r["steps"],
                latency_ms=round(r["ms"], 1),
                tokens_in=r["tokens_in"],
                tokens_out=r["tokens_out"],
                cost_usd=round(r["cost"], 6),
            )

        r = ask.answer(question)
        sources = [
            Source(
                ada=h["ada"],
                url=h["url"],
                issue_date=str(h["issue_date"]) if h["issue_date"] else None,
                expense_amount=float(h["amount"]) if h["amount"] else None,
                subject=h["content"],
            )
            for h in r["hits"]
        ]
        meta = r["meta"]
        return AskResponse(
            question=question,
            answer=r["answer"] or "",
            sufficient_evidence=not r["refused"],
            reason=r["reason"],
            sources=sources,
            tool_calls=[],
            steps=1,
            latency_ms=round(meta["encode_ms"] + meta["db_ms"] + r["llm_ms"], 1),
            tokens_in=r["tokens_in"],
            tokens_out=r["tokens_out"],
            cost_usd=round(r["cost"], 6),
        )

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Σφάλμα επεξεργασίας: {exc}")


# ─── Στατικά αρχεία ──────────────────────────────────
# ΠΑΝΤΑ τελευταίο: το mount στο "/" σκιάζει ό,τι δηλωθεί μετά από αυτό.

app.mount("/", StaticFiles(directory="static", html=True), name="static")