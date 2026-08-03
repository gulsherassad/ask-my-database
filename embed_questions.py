"""Build a local embedding cache for all BIRD dev questions.

Uses sentence-transformers (all-MiniLM-L6-v2) to embed each question's text
entirely on-device — no API calls of any kind. The resulting cache lets a
later retrieval script (e.g. "find similar past questions") load everything
it needs from a single file instead of re-embedding on every run.
"""

import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"

PROJECT_DIR = Path(__file__).resolve().parent
QUESTIONS_PATH = PROJECT_DIR / "minidev" / "MINIDEV" / "mini_dev_sqlite.json"
EVAL_TMP = PROJECT_DIR / "eval_tmp"
CACHE_PATH = EVAL_TMP / "question_embeddings.npz"

EVAL_TMP.mkdir(exist_ok=True)

# Load all BIRD dev questions
with open(QUESTIONS_PATH) as f:
    questions = json.load(f)

print(f"Loaded {len(questions)} questions from {QUESTIONS_PATH}")

# Load the local embedding model (small, CPU-friendly). Downloaded once and cached
# by sentence-transformers/huggingface on disk — no Anthropic or other API calls here.
print(f"Loading embedding model '{MODEL_NAME}'...")
model = SentenceTransformer(MODEL_NAME)

# Embed every question's text in one batch call — show_progress_bar gives live progress
texts = [item["question"] for item in questions]
embeddings = model.encode(texts, show_progress_bar=True, convert_to_numpy=True)

# Collect the parallel fields the cache needs, keyed by the same 0-based positional
# index used everywhere else in this project (predictions.json, gold.sql, diff.jsonl).
indices = np.arange(len(questions))
db_ids = np.array([item["db_id"] for item in questions])
gold_sql = np.array([item["SQL"] for item in questions])
question_texts = np.array(texts)

np.savez(
    str(CACHE_PATH),
    index=indices,
    db_id=db_ids,
    question=question_texts,
    gold_sql=gold_sql,
    embedding=embeddings,
)

print(f"Embedded {len(questions)} questions (embedding dimension: {embeddings.shape[1]})")
print(f"Saved cache to {CACHE_PATH}")
