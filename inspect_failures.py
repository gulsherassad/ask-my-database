import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

# Reuse the same absolute-path constants and gold-line fix as run_eval.py
# instead of redefining them here.
from run_eval import QUESTIONS, GOLD, DB_ROOT, EVAL_TMP, fix_gold_line

# The exact separator generate_predictions.py writes between SQL and db_id
PREDICTION_SEPARATOR = "\t----- bird -----\t"


def load_predictions():
    """Load predictions already generated in eval_tmp/predictions.json. Never calls the API."""
    predictions_path = EVAL_TMP / "predictions.json"
    with open(predictions_path) as f:
        return json.load(f)


def load_gold_lines(limit):
    """Read the first `limit` lines of GOLD, fixing space-instead-of-tab lines (same as run_eval.py)."""
    with open(GOLD) as f:
        lines = [f.readline().rstrip("\n") for _ in range(limit)]
    return [fix_gold_line(line) for line in lines]


def load_questions(limit):
    """Load question text/difficulty for the first `limit` questions."""
    with open(QUESTIONS) as f:
        all_questions = json.load(f)
    return all_questions[:limit]


def inspect(limit):
    """Run each predicted query against its gold query and categorize the outcome."""
    predictions = load_predictions()
    gold_lines = load_gold_lines(limit)
    questions = load_questions(limit)

    missing = [str(i) for i in range(limit) if str(i) not in predictions]
    if missing:
        raise SystemExit(
            f"predictions.json is missing indices {missing[:5]}{'...' if len(missing) > 5 else ''} "
            f"— it only covers fewer questions than --limit {limit}. "
            "Re-run run_eval.py with at least this limit first."
        )

    results = []

    for i in range(limit):
        question_item = questions[i]
        question_text = question_item["question"]
        difficulty = question_item["difficulty"]

        # Predicted SQL + db_id, parsed out of the "<sql>\t----- bird -----\t<db_id>" entry
        pred_sql, db_id = predictions[str(i)].split(PREDICTION_SEPARATOR, maxsplit=1)

        # Gold SQL + db_name, parsed out of the (space-fixed) gold line. db_name is always
        # the last tab-separated field, so split from the right in case the SQL itself
        # happens to contain a literal tab.
        gold_sql, _gold_db_name = gold_lines[i].rsplit("\t", maxsplit=1)

        db_path = Path(DB_ROOT) / db_id / f"{db_id}.sqlite"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(pred_sql)
            pred_rows = cursor.fetchall()
        except Exception as e:
            category = "ERROR"
            detail = str(e)
        else:
            # Predicted query ran fine — compare it against gold using the same rule
            # the official evaluator uses: set(pred) == set(gold).
            cursor.execute(gold_sql)
            gold_rows = cursor.fetchall()
            if set(pred_rows) == set(gold_rows):
                category = "CORRECT"
                detail = None
            else:
                category = "WRONG_RESULT"
                detail = f"pred returned {len(pred_rows)} rows, gold returned {len(gold_rows)} rows"

        conn.close()

        results.append(
            {
                "index": i,
                "difficulty": difficulty,
                "question": question_text,
                "pred_sql": pred_sql,
                "gold_sql": gold_sql,
                "category": category,
                "detail": detail,
            }
        )

    return results


def print_summary(results):
    """Overall and per-difficulty tallies of CORRECT / WRONG_RESULT / ERROR."""
    overall = Counter(r["category"] for r in results)
    by_difficulty = {}
    for r in results:
        by_difficulty.setdefault(r["difficulty"], Counter())[r["category"]] += 1

    print("=" * 70)
    print(f"SUMMARY ({len(results)} questions)")
    print("=" * 70)
    print(
        f"CORRECT: {overall.get('CORRECT', 0)}   "
        f"WRONG_RESULT: {overall.get('WRONG_RESULT', 0)}   "
        f"ERROR: {overall.get('ERROR', 0)}"
    )
    print("\nBy difficulty:")
    for difficulty in sorted(by_difficulty):
        counts = by_difficulty[difficulty]
        print(
            f"  {difficulty:<12} "
            f"CORRECT: {counts.get('CORRECT', 0):<3} "
            f"WRONG_RESULT: {counts.get('WRONG_RESULT', 0):<3} "
            f"ERROR: {counts.get('ERROR', 0):<3}"
        )
    print()


def print_failure_details(results):
    """One readable block per non-correct question: question, both SQLs, and the failure detail."""
    failures = [r for r in results if r["category"] != "CORRECT"]
    if not failures:
        print("No failures — every prediction matched its gold result.")
        return

    print("=" * 70)
    print(f"FAILURE DETAILS ({len(failures)} questions)")
    print("=" * 70)

    for r in failures:
        print("-" * 70)
        print(f"Index: {r['index']}   Difficulty: {r['difficulty']}   Category: {r['category']}")
        print(f"Question: {r['question']}")
        print(f"\nPredicted SQL:\n  {r['pred_sql']}")
        print(f"\nGold SQL:\n  {r['gold_sql']}")
        print(f"\nDetail: {r['detail']}")
    print("-" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Diagnose why predictions failed, reusing eval_tmp/predictions.json (no API calls)."
    )
    parser.add_argument("--limit", type=int, default=50, help="Number of questions to inspect (default: 50)")
    args = parser.parse_args()

    results = inspect(args.limit)
    print_summary(results)
    print_failure_details(results)


if __name__ == "__main__":
    main()
