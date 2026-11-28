#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
python3.12 -m unittest -v test_secret_scan
python3.12 .github/scripts/test-scaffold-ci.py
node --test files/.opencode/plugins/*/*.test.mjs
node --test .github/scripts/ai-review.test.cjs
