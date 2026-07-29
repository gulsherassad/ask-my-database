import argparse
import json
import re
import sqlite3
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

# Load environment variables (expects ANTHROPIC_API_KEY in .env)
load_dotenv()

client = Anthropic()


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


MAX_SAMPLE_ROWS = 3
MAX_CELL_LEN = 50


def truncate_cell(value) -> str:
    """Render one cell for the sample preview, truncating long text and labeling NULLs."""
    if value is None:
        return "NULL"
    text = str(value)
    if len(text) > MAX_CELL_LEN:
        text = text[:MAX_CELL_LEN] + "…"
    return text


def get_sample_rows(cursor: sqlite3.Cursor, table_name: str) -> str:
    """Fetch up to MAX_SAMPLE_ROWS rows from a table as a compact "col | col" preview.

    Returns "" if the table is empty or the query fails, so callers can skip it.
    """
    try:
        cursor.execute(f'SELECT * FROM "{table_name}" LIMIT {MAX_SAMPLE_ROWS}')
        rows = cursor.fetchall()
    except sqlite3.Error:
        return ""

    if not rows:
        return ""

    columns = [col[0] for col in cursor.description]
    lines = [" | ".join(columns)]
    for row in rows:
        lines.append(" | ".join(truncate_cell(value) for value in row))
    return "\n".join(lines)


def get_schema(db_id: str) -> str:
    """Fetch each table's CREATE TABLE statement plus a few sample rows.

    Sample rows let the model see the real stored format of values (date
    formats, string casing, etc.) rather than guessing from column names alone.
    """
    db_path = Path("minidev/MINIDEV/dev_databases") / db_id / f"{db_id}.sqlite"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'")
    tables = cursor.fetchall()

    schema_parts = []
    for table_name, create_sql in tables:
        if create_sql is None:
            continue
        part = create_sql
        sample = get_sample_rows(cursor, table_name)
        if sample:
            part += f"\n-- Sample rows from {table_name}:\n{sample}"
        schema_parts.append(part)

    conn.close()
    return "\n\n".join(schema_parts)


def generate_sql(schema: str, evidence: str, question: str) -> str:
    """Ask Claude for a single raw SQLite query, with markdown fences stripped."""
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


# Parse --limit so we can test on a handful of questions before scaling up
parser = argparse.ArgumentParser(description="Generate a BIRD-style predictions.json file.")
parser.add_argument("--limit", type=int, default=5, help="Number of questions to process (default: 5)")
args = parser.parse_args()

# Load all questions and take the first --limit of them
questions_path = Path("minidev/MINIDEV/mini_dev_sqlite.json")
with open(questions_path) as f:
    questions = json.load(f)

questions = questions[: args.limit]

predictions = {}

for i, item in enumerate(questions):
    db_id = item["db_id"]
    evidence = item["evidence"]
    question = item["question"]

    schema = get_schema(db_id)
    sql_query = generate_sql(schema, evidence, question)

    # Flatten to a single line — the predictions file must not contain raw newlines
    sql_query = sql_query.replace("\n", " ")

    # BIRD's expected format: <sql>\t----- bird -----\t<db_id>
    predictions[str(i)] = f"{sql_query}\t----- bird -----\t{db_id}"

    print(f"{i + 1}/{len(questions)} done")

# Save the predictions
output_path = Path("predictions.json")
with open(output_path, "w") as f:
    json.dump(predictions, f, indent=2)

print(f"Saved {len(predictions)} predictions to {output_path}")
