import argparse
import json
from pathlib import Path

# Reuse the shared schema-fetch/prompt/fence-stripping logic — this file owns
# only the batch-generation loop (resume support, --limit, incremental save).
from sql_generation import generate_sql, get_schema

# Parse --limit so we can test on a handful of questions before scaling up
parser = argparse.ArgumentParser(description="Generate a BIRD-style predictions.json file.")
parser.add_argument("--limit", type=int, default=5, help="Number of questions to process (default: 5)")
parser.add_argument(
    "--few-shot",
    action="store_true",
    help="Retrieve 3 similar same-database questions and inject them into the prompt as worked examples.",
)
args = parser.parse_args()

# Only import retrieval.py (which loads the embedding cache at import time) when
# actually needed, so a plain run still works if the cache hasn't been built yet.
if args.few_shot:
    from retrieval import retrieve_examples

# Load all questions and take the first --limit of them
questions_path = Path("minidev/MINIDEV/mini_dev_sqlite.json")
with open(questions_path) as f:
    questions = json.load(f)

questions = questions[: args.limit]

# Resume support: load any predictions already on disk so a re-run can pick up
# where an interrupted run left off, instead of regenerating everything.
output_path = Path("predictions.json")
if output_path.exists():
    with open(output_path) as f:
        predictions = json.load(f)
else:
    predictions = {}

SAVE_EVERY = 10  # flush progress to disk this often, so an interruption only loses a few questions

generated_count = 0
skipped_count = 0

for i, item in enumerate(questions):
    idx = str(i)

    if idx in predictions:
        # Already generated in a previous run — keep the existing entry, skip the API call
        skipped_count += 1
        print(f"{i + 1}/{len(questions)} done (skipped, already exists) — generated: {generated_count}, skipped: {skipped_count}")
    else:
        db_id = item["db_id"]
        evidence = item["evidence"]
        question = item["question"]

        schema = get_schema(db_id)

        # `i` is this question's own position — passing it as the query index is what
        # makes retrieval's leave-one-out exclusion work correctly per question.
        examples = retrieve_examples(i, k=3, same_db_only=True) if args.few_shot else None

        sql_query = generate_sql(schema, question, evidence=evidence, examples=examples)

        # Flatten to a single line — the predictions file must not contain raw newlines
        sql_query = sql_query.replace("\n", " ")

        # BIRD's expected format: <sql>\t----- bird -----\t<db_id>
        predictions[idx] = f"{sql_query}\t----- bird -----\t{db_id}"

        generated_count += 1
        print(f"{i + 1}/{len(questions)} done (generated) — generated: {generated_count}, skipped: {skipped_count}")

    # Save incrementally so an interrupted run leaves a resumable partial file
    if (i + 1) % SAVE_EVERY == 0 or (i + 1) == len(questions):
        with open(output_path, "w") as f:
            json.dump(predictions, f, indent=2)

print(
    f"Saved {len(predictions)} predictions to {output_path} "
    f"(this run — generated: {generated_count}, skipped: {skipped_count})"
)
