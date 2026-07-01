#!/usr/bin/env bash
# Compare HolmesGPT alone vs +woodpecker on a live crashloop, scored for
# blast-radius recall against ground truth.
#
#   ./compare.sh db [runs]        # scenario crashloop-db, N runs per arm (default 3)
#
# Injects the fault, runs Holmes N times in each arm on the SAME live incident,
# heals, then scores recall + consistency. Same model + prompt both arms; only
# the woodpecker toolset differs.
set -euo pipefail
cd "$(dirname "$0")"

SVC="${1:?service, e.g. db|catalog|orders}"; RUNS="${2:-3}"
SID="crashloop-$SVC"; NS=ecommerce
PROMPT="Investigate the current incident in the $NS namespace. Identify the single root-cause service and every service affected by it (the blast radius). End your reply with exactly two lines:
ROOT: <service>
AFFECTED: <comma-separated affected services>"

mkdir -p logs
echo "== inject $SID, settle 45s =="
python fault.py inject "$SID"
sleep 45

for arm in alone wp; do
  for i in $(seq 1 "$RUNS"); do
    echo "== holmes $arm run $i =="
    ./run.sh "$arm" "$PROMPT" "logs/${SVC}-${arm}-${i}.log" >/dev/null 2>&1 || echo "  (run failed)"
  done
done

echo "== heal ==" && python fault.py heal "$SID"

echo ""; echo "############ Holmes ALONE ############"
python score_holmes.py --fault "$SVC" logs/${SVC}-alone-*.log
echo ""; echo "############ Holmes + WOODPECKER ############"
python score_holmes.py --fault "$SVC" logs/${SVC}-wp-*.log
