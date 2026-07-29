import json
import re
import sqlite3
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

# Step 1: load environment variables (expects ANTHROPIC_API_KEY in .env)
load_dotenv()


def strip_markdown_fences(text: str) -> str:
    """Strip a leading/trailing ```sql or ``` code fence, if present."""
    stripped = text.strip()
    match = re.match(r"^```(?:sql)?\s*\n(.*)\n```$", stripped, re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped

# Step 2: load the questions file and take the first question
questions_path = Path("minidev/MINIDEV/mini_dev_sqlite.json")
with open(questions_path) as f:
    questions = json.load(f)

first_question = questions[0]

# Step 3: print the question's fields
question_text = first_question["question"]
db_id = first_question["db_id"]
evidence = first_question["evidence"]

print("Question:", question_text)
print("DB ID:", db_id)
print("Evidence:", evidence)

# Step 4: open the corresponding SQLite database
db_path = Path("minidev/MINIDEV/dev_databases") / db_id / f"{db_id}.sqlite"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Step 5: query the schema (CREATE TABLE statements) and print it
cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table'")
schema_rows = cursor.fetchall()
schema = "\n\n".join(row[0] for row in schema_rows if row[0] is not None)

print("\nSchema:")
print(schema)

# Step 6: ask Claude to generate a SQL query for the question
client = Anthropic()

prompt = f"""You are given a SQLite database schema, some evidence (hints), and a question.
Return ONLY a single SQLite query that answers the question. Do not include any
explanation, markdown formatting, code fences, or anything other than the raw SQL query.

Schema:
{schema}

Evidence:
{evidence}

Question:
{question_text}
"""

response = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=1024,
    messages=[{"role": "user", "content": prompt}],
)

sql_query = next(block.text for block in response.content if block.type == "text").strip()
sql_query = strip_markdown_fences(sql_query)

print("\nGenerated SQL:")
print(sql_query)

# Step 7: run the generated SQL against the database and print the results
print("\nQuery results:")
try:
    cursor.execute(sql_query)
    rows = cursor.fetchall()
    for row in rows:
        print(row)
except sqlite3.Error as e:
    print("SQL error:", e)

conn.close()
