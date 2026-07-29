import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# --- Paths (absolute, built from the home directory, so this works from anywhere) ---
PROJECT_DIR = Path.home() / "Desktop" / "ask-my-database"
BIRD_EVAL_DIR = Path.home() / "Desktop" / "bird-official" / "evaluation"
QUESTIONS = PROJECT_DIR / "minidev" / "MINIDEV" / "mini_dev_sqlite.json"
GOLD = PROJECT_DIR / "minidev" / "MINIDEV" / "mini_dev_sqlite_gold.sql"
# Built as a plain string (not Path) so the trailing slash the evaluator expects is preserved
DB_ROOT = f"{PROJECT_DIR}/minidev/MINIDEV/dev_databases/"
EVAL_TMP = PROJECT_DIR / "eval_tmp"

EVAL_TMP.mkdir(exist_ok=True)


def fix_gold_line(line: str) -> str:
    """Fix gold lines that use a space instead of a tab before the db_name.

    Leaves lines that already contain a tab untouched. For broken lines, the
    db_name is the last whitespace-separated token — replace the last run of
    spaces before it with a single tab.
    """
    if "\t" in line:
        return line
    match = re.match(r"^(.*\S)( +)(\S+)$", line)
    if not match:
        return line
    sql_part, _spaces, db_name = match.groups()
    return f"{sql_part}\t{db_name}"


def main():
    parser = argparse.ArgumentParser(description="Generate predictions and score them with the BIRD EX evaluator.")
    parser.add_argument("--limit", type=int, default=10, help="Number of questions to evaluate (default: 10)")
    args = parser.parse_args()
    limit = args.limit

    # Step 1: reuse generate_predictions.py (as a subprocess) to build predictions
    # for the first `limit` questions. It writes predictions.json into PROJECT_DIR
    # by default, so move that file into eval_tmp/ afterward.
    subprocess.run(
        [sys.executable, str(PROJECT_DIR / "generate_predictions.py"), "--limit", str(limit)],
        cwd=PROJECT_DIR,
        check=True,
    )
    generated_predictions = PROJECT_DIR / "predictions.json"
    predictions_path = EVAL_TMP / "predictions.json"
    shutil.move(str(generated_predictions), str(predictions_path))

    # Step 2: take the first `limit` lines of the gold file, fixing any that use
    # a space instead of a tab before the db_name, and write them to eval_tmp/gold.sql
    with open(GOLD) as f:
        gold_lines = [f.readline().rstrip("\n") for _ in range(limit)]
    gold_lines = [fix_gold_line(line) for line in gold_lines]

    gold_path = EVAL_TMP / "gold.sql"
    with open(gold_path, "w") as f:
        f.write("\n".join(gold_lines) + "\n")

    # Step 3: write the first `limit` questions as JSONL (the evaluator's difficulty file)
    with open(QUESTIONS) as f:
        all_questions = json.load(f)
    questions = all_questions[:limit]

    diff_path = EVAL_TMP / "diff.jsonl"
    with open(diff_path, "w") as f:
        for item in questions:
            f.write(json.dumps(item) + "\n")

    # Step 4: run the official evaluator, streaming its output straight to our terminal.
    # Flush explicitly — otherwise this print can sit in Python's buffer and appear
    # after the subprocess's output, which writes directly to the inherited stdout.
    print(f"\n{'=' * 60}")
    print(f"EX evaluation on first {limit} questions")
    print(f"{'=' * 60}\n", flush=True)

    subprocess.run(
        [
            sys.executable,
            "evaluation_ex.py",
            "--predicted_sql_path", str(predictions_path),
            "--ground_truth_path", str(gold_path),
            "--db_root_path", DB_ROOT,
            "--diff_json_path", str(diff_path),
            "--sql_dialect", "SQLite",
            "--num_cpus", "1",
        ],
        cwd=BIRD_EVAL_DIR,
        check=True,
    )


if __name__ == "__main__":
    main()
