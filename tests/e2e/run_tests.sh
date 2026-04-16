#!/usr/bin/env bash
# Build the mc-helper-e2e container and run the e2e test suite.
#
# Usage:
#   bash tests/e2e/run_tests.sh                       # run all tests
#   bash tests/e2e/run_tests.sh -k test_server_pack_gtnh  # run one test
#   CF_API_KEY=xxx bash tests/e2e/run_tests.sh        # include CurseForge test
#
# Environment variables:
#   CONTAINER_RUNTIME  — override container runtime (default: podman or docker)
#   E2E_OUTPUT_DIR     — host dir mounted as /tmp/e2e-output (default: /tmp/e2e-output)
#   CF_API_KEY         — CurseForge API key (enables the All of Create test)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-}"
if [ -z "$CONTAINER_RUNTIME" ]; then
    if command -v podman &>/dev/null; then
        CONTAINER_RUNTIME=podman
    elif command -v docker &>/dev/null; then
        CONTAINER_RUNTIME=docker
    else
        echo "ERROR: neither podman nor docker found on PATH" >&2
        exit 1
    fi
fi

IMAGE=mc-helper-e2e

echo "==> Building $IMAGE with $CONTAINER_RUNTIME..."
"$CONTAINER_RUNTIME" build -t "$IMAGE" -f "$SCRIPT_DIR/Containerfile" "$REPO_ROOT"

echo "==> Running e2e tests..."
"$CONTAINER_RUNTIME" run --rm \
    -e CF_API_KEY="${CF_API_KEY:-}" \
    "$IMAGE" \
    pytest tests/e2e/test_e2e.py -v --tb=short "$@"
