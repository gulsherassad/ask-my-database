"""Shared SQL-generation logic: schema fetching, prompting Claude, and cleaning
up its response. This is the single source of truth for both
generate_predictions.py (offline batch scoring) and server.py (the live query
API) — neither should redefine this logic.
"""

import re
import sqlite3
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

# Load environment variables (expects ANTHROPIC_API_KEY in .env)
load_dotenv()

client = Anthropic()

# Absolute paths, resolved from this file's location, so callers work no
# matter what directory they were started from (e.g. a plain script vs uvicorn).
PROJECT_DIR = Path(__file__).resolve().parent
DB_ROOT = PROJECT_DIR / "minidev" / "MINIDEV" / "dev_databases"


LEADING_FENCE_RE = re.compile(r"^```(?:sql)?\s*", re.IGNORECASE)
TRAILING_FENCE_RE = re.compile(r"\s*```\s*$")


def strip_markdown_fences(text: str) -> str:
    """Strip a leading/trailing triple-backtick code fence (```sql or ```), if present.

    The leading and trailing fence are stripped independently (not as a
    matched pair), so this also handles a fence the model left unclosed.
    Content may be on the same line as the backticks or on its own line,
    with or without a language tag. Leaves the string unchanged (aside from
    trimming) if there is no fence.
    """
    stripped = text.strip()
    stripped = LEADING_FENCE_RE.sub("", stripped, count=1)
    stripped = TRAILING_FENCE_RE.sub("", stripped, count=1)
    return stripped.strip()


def get_schema(db_id: str) -> str:
    """Fetch the CREATE TABLE statements for a database."""
    db_path = DB_ROOT / db_id / f"{db_id}.sqlite"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table'")
    schema_rows = cursor.fetchall()
    conn.close()
    return "\n\n".join(row[0] for row in schema_rows if row[0] is not None)


def generate_sql(schema: str, question: str, evidence: str = "") -> str:
    """Ask Claude for a single raw SQLite query, with markdown fences stripped.

    `evidence` is the optional BIRD-style hint string used during batch
    generation; it's omitted (empty) for freeform questions asked through the
    live query API.
    """
    prompt = f"""You are given a SQLite database schema, some evidence (hints), and a question.
Return ONLY a single SQLite query that answers the question. Do not include any
explanation, markdown formatting, code fences, or anything other than the raw SQL query.

When a column is a foreign key (e.g. a `..._id` or `link_to_...` column that references
another table) and the question asks for a human-readable attribute (a name, title, or
description) rather than an ID, JOIN to the referenced table and return that
human-readable value instead of the raw ID.

Match literal values from the question against the exact string as it is stored in the
data — the question may phrase a value more briefly than the data does (e.g. the question
says "Orange" but the column stores "Orange County"). Prefer the full/exact form as it
would appear in the data; do not truncate or reformat values from the question.

Schema:
{schema}

Evidence:
{evidence}

Question:
{question}
"""

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    sql_query = next(block.text for block in response.content if block.type == "text").strip()
    return strip_markdown_fences(sql_query)
