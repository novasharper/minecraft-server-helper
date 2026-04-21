#!/usr/bin/env python3
# Thin wrapper: adds /app/src (bind-mounted at runtime) to sys.path and invokes
# mc_helper.cli.main with verbose logging always enabled for e2e visibility.

import sys

sys.path.insert(0, "/app/src")
sys.argv.insert(1, "-v")

from mc_helper.cli import main

main()
