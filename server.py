"""FastAPI backend for Querybird.

Serves the static frontend and exposes the natural-language-to-SQL query API.
All SQL generation (schema fetch, prompting, fence-stripping) is reused from
sql_generation.py — this file only adds the web layer and the safety checks
around executing model-generated SQL.
"""

import re
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sql_generation import DB_ROOT, PROJECT_DIR, generate_sql, get_schema

FRONTEND_DIR = PROJECT_DIR / "frontend"

# --- Safety limits for executing model-generated SQL ------------------------
ROW_LIMIT = 200
QUERY_TIMEOUT_SECONDS = 10

# Keywords that would mutate the database or the SQLite session — blocked
# even though the connection is already opened read-only, as defense in depth.
FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "REPLACE", "TRUNCATE", "PRAGMA", "ATTACH", "DETACH", "VACUUM", "REINDEX",
}


def list_databases() -> list[str]:
    """db_ids are the subfolders of DB_ROOT that actually contain a matching .sqlite file."""
    if not DB_ROOT.exists():
        return []
    return sorted(
        p.name
        for p in DB_ROOT.iterdir()
        if p.is_dir() and (p / f"{p.name}.sqlite").exists()
    )


def validate_select_only(sql: str) -> None:
    """Raise ValueError unless `sql` is a single read-only SELECT (optionally via a WITH CTE)."""
    body = sql.strip()
    if body.endswith(";"):
        body = body[:-1]

    # A semicolon anywhere in what's left means more than one statement was stacked.
    if ";" in body:
        raise ValueError("Only a single SQL statement is allowed.")

    match = re.match(r"\s*(\w+)", body)
    first_word = match.group(1).upper() if match else ""
    if first_word not in {"SELECT", "WITH"}:
        raise ValueError(f"Only SELECT queries are allowed (got {first_word or 'an empty query'!r}).")

    # Defense in depth: also block dangerous keywords wherever they appear
    # (e.g. inside a subquery), not just at the start of the statement.
    tokens = {tok.upper() for tok in re.findall(r"[A-Za-z_]+", body)}
    blocked = tokens & FORBIDDEN_KEYWORDS
    if blocked:
        raise ValueError(f"Query contains disallowed keyword(s): {', '.join(sorted(blocked))}")


def json_safe_cell(value):
    """SQLite can return bytes for BLOB columns; JSON can't encode those directly."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_readonly_query(db_id: str, sql: str):
    """Execute `sql` against db_id's SQLite file: read-only, timed out, and row-capped."""
    db_path = DB_ROOT / db_id / f"{db_id}.sqlite"
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    start = time.monotonic()

    def abort_if_slow(*_args) -> int:
        # A non-zero return from a progress handler aborts the running query.
        return 1 if time.monotonic() - start > QUERY_TIMEOUT_SECONDS else 0

    conn.set_progress_handler(abort_if_slow, 1000)

    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description] if cursor.description else []
        raw_rows = cursor.fetchmany(ROW_LIMIT)
        rows = [[json_safe_cell(cell) for cell in row] for row in raw_rows]
        elapsed_ms = round((time.monotonic() - start) * 1000)
        return columns, rows, elapsed_ms
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e).lower():
            raise TimeoutError(f"Query timed out after {QUERY_TIMEOUT_SECONDS}s") from e
        raise
    finally:
        conn.close()


# --- FastAPI app --------------------------------------------------------------
app = FastAPI(title="Querybird")


class QueryRequest(BaseModel):
    question: str
    database: str


@app.get("/api/databases")
def api_databases():
    return {"databases": list_databases()}


@app.post("/api/query")
def api_query(req: QueryRequest):
    sql_query = None  # not generated yet — stays None if generation itself fails
    try:
        if req.database not in list_databases():
            raise ValueError(f"Unknown database '{req.database}'.")

        schema = get_schema(req.database)
        sql_query = generate_sql(schema, req.question)  # fence-stripping happens inside generate_sql

        validate_select_only(sql_query)

        columns, rows, elapsed_ms = run_readonly_query(req.database, sql_query)
        return {
            "sql": sql_query,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "elapsed_ms": elapsed_ms,
        }
    except Exception as e:
        # Always 200 — the frontend shows the generated SQL (if we got one) even
        # when validation or execution fails, rather than treating it as a hard error.
        return {"sql": sql_query, "error": str(e)}


# Mounted last (and at "/") so it doesn't shadow the /api/* routes above; html=True
# serves frontend/index.html for "/" and any other unmatched path under the mount.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
