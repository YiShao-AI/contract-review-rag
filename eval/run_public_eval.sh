#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

eval_data_dir="${EVAL_DATA_DIR:-$repo_dir/.eval-data}"
case "$eval_data_dir" in
  "$repo_dir"/.eval-data|"$repo_dir"/.eval-data/*) ;;
  *) echo "EVAL_DATA_DIR must remain inside $repo_dir/.eval-data" >&2; exit 2 ;;
esac

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

rm -rf -- "$eval_data_dir"
mkdir -p "$eval_data_dir"
export DATA_DIR="$eval_data_dir"
export TOP_K=5
export CHUNK_SIZE=1000
export CHUNK_OVERLAP=150
export RERANK=0
export EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"

.venv/bin/python eval/build_eval_index.py --corpus eval/corpus
.venv/bin/python eval/eval_retrieval.py --json-out eval/results.local.json

echo "Local results written to eval/results.local.json"
