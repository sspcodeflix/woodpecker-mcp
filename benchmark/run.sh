#!/usr/bin/env bash
# Run HolmesGPT on the live cluster in one arm and tee a labeled log.
#
#   ./run.sh alone "<prompt>" out.log     # woodpecker toolset disabled
#   ./run.sh wp    "<prompt>" out.log     # woodpecker toolset enabled
#
# The only difference between arms is the woodpecker-graph toolset's enabled flag
# in ~/.holmes/config.yaml - same model, same prompt.
set -euo pipefail
cd "$(dirname "$0")"

ARM="${1:?arm: alone|wp}"; PROMPT="${2:?prompt}"; OUT="${3:-/dev/stdout}"
CFG="$HOME/.holmes/config.yaml"
HOLMES="${HOLMES:-/home/soumya/Documents/AI_Projects/holmes-venv/bin/holmes}"

case "$ARM" in
  wp)    sed -i 's/enabled: false/enabled: true/'  "$CFG";;
  alone) sed -i 's/enabled: true/enabled: false/' "$CFG";;
  *) echo "arm must be 'alone' or 'wp'"; exit 1;;
esac

# LLM: litellm native DeepSeek provider; clear any polluted OpenAI vars.
unset OPENAI_API_KEY OPENAI_API_BASE OPENAI_BASE_URL DEEPSEEK_API_BASE DEEPSEEK_BASE_URL
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-$(grep -m1 '^DEEPSEEK_API_KEY=' .env | cut -d= -f2-)}"
export MODEL="deepseek/deepseek-chat"
[ -n "$DEEPSEEK_API_KEY" ] || { echo "set DEEPSEEK_API_KEY in benchmark/.env"; exit 1; }

"$HOLMES" ask "$PROMPT" --model deepseek/deepseek-chat -v -n 2>&1 | tee "$OUT"
