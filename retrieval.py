"""Retrieve the most similar past questions for few-shot prompting.

Uses the local embedding cache built by embed_questions.py — no API calls,
just numpy cosine similarity over an in-memory matrix (fine at this scale;
no vector database needed for ~500 rows).
"""

from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parent
CACHE_PATH = PROJECT_DIR / "eval_tmp" / "question_embeddings.npz"

# Load the cache once at import time — it's small (~500 x 384 floats), so this is cheap.
_cache = np.load(CACHE_PATH, allow_pickle=False)
INDEX = _cache["index"]
DB_ID = _cache["db_id"]
QUESTION = _cache["question"]
GOLD_SQL = _cache["gold_sql"]
EMBEDDING = _cache["embedding"]

# Pre-normalize every embedding once so cosine similarity reduces to a plain dot product.
_norms = np.linalg.norm(EMBEDDING, axis=1, keepdims=True)
_UNIT_EMBEDDINGS = EMBEDDING / _norms


def retrieve_examples(query_index: int, k: int = 3, same_db_only: bool = True) -> list[dict]:
    """Find the top-k questions most similar to the one at `query_index`.

    Never returns the query question itself — including it would leak the
    answer to the very question being asked. If same_db_only, candidates are
    restricted to the query's db_id, since same-database examples are what
    teach a model that database's conventions (column names, value formats).
    """
    query_vector = _UNIT_EMBEDDINGS[query_index]

    # Cosine similarity of the (already unit-norm) query against every row at once.
    similarities = _UNIT_EMBEDDINGS @ query_vector

    candidate_mask = np.ones(len(INDEX), dtype=bool)
    candidate_mask[query_index] = False  # never return the question itself

    if same_db_only:
        candidate_mask &= DB_ID == DB_ID[query_index]

    candidate_positions = np.where(candidate_mask)[0]

    # Rank candidates by similarity, descending, and keep the top k.
    ranked = candidate_positions[np.argsort(-similarities[candidate_positions])]
    top_positions = ranked[:k]

    return [
        {
            "index": int(INDEX[i]),
            "db_id": str(DB_ID[i]),
            "question": str(QUESTION[i]),
            "gold_sql": str(GOLD_SQL[i]),
            "similarity": float(similarities[i]),
        }
        for i in top_positions
    ]


if __name__ == "__main__":
    # Demo: pick one question, show what retrieval would surface for it, so it's
    # easy to eyeball whether the retrieved examples are actually topically similar.
    demo_index = 0

    print(f"Query question (index {demo_index}):")
    print(f"  [{DB_ID[demo_index]}] {QUESTION[demo_index]}")
    print(f"  gold SQL: {GOLD_SQL[demo_index]}")

    examples = retrieve_examples(demo_index, k=3, same_db_only=True)

    print(f"\nTop {len(examples)} similar questions (same database only):")
    for rank, example in enumerate(examples, start=1):
        print(f"\n{rank}. index {example['index']}  (similarity {example['similarity']:.3f})")
        print(f"   Q:   {example['question']}")
        print(f"   SQL: {example['gold_sql']}")
