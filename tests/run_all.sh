#!/usr/bin/env bash
# Every check in one command: production build, preview build, JavaScript
# type check, and the full pytest suite (build + real-browser tests).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Production build";  python3 build.py
echo "== Preview build";     python3 build.py --preview
echo "== JavaScript syntax"; node --check src/site.js
echo "== JavaScript types (tsc --checkJs, strict)"
if command -v tsc >/dev/null 2>&1; then tsc -p tsconfig.json
elif [ -f /opt/npm-tools/node_modules/typescript/bin/tsc ]; then node /opt/npm-tools/node_modules/typescript/bin/tsc -p tsconfig.json
else npx --yes --package=typescript@5.6.3 tsc -p tsconfig.json; fi
echo "   0 type errors"
echo "== Tests"; python3 -m pytest tests -q -p no:cacheprovider
