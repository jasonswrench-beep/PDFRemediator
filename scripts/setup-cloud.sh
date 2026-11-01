#!/usr/bin/env bash
# Source-only development setup. This does not install PDF tagging/OCR engines.
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "${script_dir}/.." && pwd)"
cd -- "${repo_dir}"
test -f pyproject.toml
test -d src/pdf_remediator

# Developer tests execute the shipped JavaScript without a browser or packages.
if ! command -v node >/dev/null 2>&1; then
  printf '%s\n' 'Node.js 20 or newer is required for browser-script regression tests.' >&2
  exit 1
fi
node -e 'if (Number(process.versions.node.split(".")[0]) < 20) { console.error("Node.js 20 or newer is required for browser-script regression tests."); process.exit(1); }'

python_bin="${PDF_REMEDIATOR_PYTHON:-python3}"
"${python_bin}" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11 or newer is required"'
"${python_bin}" -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -e '.[test]'

printf '%s\n' \
  'Python development environment ready in .venv.' \
  'Run: .venv/bin/python scripts/test-cloud.py (includes Node browser-script tests)' \
  'Native tagging, veraPDF, OCR, local AI models, and private documents are not installed.'
