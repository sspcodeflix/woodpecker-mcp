#!/usr/bin/env bash
# Inject / heal faults in the ecommerce-demo cluster for the benchmark.
#
#   ./inject.sh db          # Postgres crashloop  -> cascade, root = db
#   ./inject.sh payments    # mid-tier crashloop  -> root = payments
#   ./inject.sh orders      # bad image tag        -> root = orders (shallow)
#   ./inject.sh heal        # restore everything
set -euo pipefail
NS="${NS:-ecommerce}"

case "${1:-}" in
  db)
    kubectl -n "$NS" patch deployment db --type=json \
      -p='[{"op":"add","path":"/spec/template/spec/containers/0/args","value":["-c","bogus_setting=on"]}]'
    ;;
  payments)
    kubectl -n "$NS" patch deployment payments --type=json \
      -p='[{"op":"add","path":"/spec/template/spec/containers/0/command","value":["sh","-c","exit 1"]}]'
    ;;
  orders)
    kubectl -n "$NS" set image deployment/orders orders=ecommerce-demo-svc:nope
    ;;
  heal)
    kubectl -n "$NS" patch deployment db --type=json \
      -p='[{"op":"remove","path":"/spec/template/spec/containers/0/args"}]' 2>/dev/null || true
    kubectl -n "$NS" patch deployment payments --type=json \
      -p='[{"op":"remove","path":"/spec/template/spec/containers/0/command"}]' 2>/dev/null || true
    kubectl -n "$NS" set image deployment/orders orders=ecommerce-demo-svc:latest 2>/dev/null || true
    ;;
  *)
    echo "usage: $0 {db|payments|orders|heal}"; exit 1;;
esac
echo "done - wait ~40s for the cascade to settle, then: python verify.py --fault <service>"
