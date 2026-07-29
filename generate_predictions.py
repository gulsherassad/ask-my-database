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


def strip_markdown_fences(text: str) -> str:
    """Strip a leading/trailing ```sql or ``` code fence, if present."""
    stripped = text.strip()
    match = re.match(r"^```(?:sql)?\s*\n(.*)\n```$", stripped, re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped


def get_schema(db_id: str) -> str:
    """Fetch the CREATE TABLE statements for a database."""
    db_path = Path("minidev/MINIDEV/dev_databases") / db_id / f"{db_id}.sqlite"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table'")
    schema_rows = cursor.fetchall()
    conn.close()
    return "\n\n".join(row[0] for row in schema_rows if row[0] is not None)


def generate_sql(schema: str, evidence: str, question: str) -> str:
    """Ask Claude for a single raw SQLite query, with markdown fences stripped."""
    prompt = f"""You are given a SQLite database schema, some evidence (hints), and a question.
Return ONLY a single SQLite query that answers the question. Do not include any
explanation, markdown formatting, code fences, or anything other than the raw SQL query.

Schema:
{schema}

Evidence:
{evidence}

Question:
{question}
"""

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
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
