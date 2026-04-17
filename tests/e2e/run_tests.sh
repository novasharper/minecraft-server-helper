#!/usr/bin/env bash
# Run the e2e test suite on the host.  The mc-helper-e2e image is built
# automatically by the pytest session fixture on first run.
#
# Usage:
#   bash tests/e2e/run_tests.sh                           # run all tests
#   bash tests/e2e/run_tests.sh -k test_server_vanilla    # run one test
#   CF_API_KEY=xxx bash tests/e2e/run_tests.sh            # include CurseForge test
#
# Environment variables:
#   CONTAINER_RUNTIME  — override container runtime (default: podman or docker)
#   E2E_OUTPUT_DIR     — host dir for server output (default: auto temp dir)
#   E2E_LIVE_OUTPUT    — set to 1 to stream container output as tests run
#   CF_API_KEY         — CurseForge API key (enables the All of Create test)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$REPO_ROOT"
exec poetry run pytest tests/e2e/test_e2e.py -v --tb=short "$@"
