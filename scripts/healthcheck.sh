#!/usr/bin/env bash
# Quick health check for all services. Run after `docker compose up`.
set -e

BASE="http://localhost"
PASS=0; FAIL=0

check() {
  local name=$1 url=$2
  if curl -sf "$url" > /dev/null 2>&1; then
    echo "✅  $name"
    PASS=$((PASS+1))
  else
    echo "❌  $name  ($url)"
    FAIL=$((FAIL+1))
  fi
}

echo "=== FuelChain Guardian — Service Health Check ==="
echo ""
check "Backend API"       "$BASE:8000/health"
check "Readiness probe"   "$BASE:8000/ready"
check "API Docs"          "$BASE:8000/docs"
check "Prometheus metrics""$BASE:8000/metrics"
check "Panic NLP"         "$BASE:8001/health"
check "WebSocket Gateway" "$BASE:8002/health"
check "Mock OMC"          "$BASE:8003/health"
check "React Dashboard"   "$BASE:3000"
check "Grafana"           "$BASE:3001"
check "Redpanda Console"  "$BASE:8080"
check "Prometheus"        "$BASE:9090/-/healthy"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && echo "🎉  All services healthy!" || echo "⚠️   Some services are not ready yet."
exit $FAIL
