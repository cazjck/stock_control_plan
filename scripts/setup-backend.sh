#!/usr/bin/env bash
# Tạo virtualenv cho backend và cài thư viện. Xử lý được máy thiếu gói python3-venv (không có ensurepip):
# khi đó tạo venv không pip rồi nạp pip từ wheel chính thức trên PyPI, có kiểm tra sha256.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-$ROOT/backend/.venv}"
PY="${PYTHON:-python3}"

if [ ! -x "$VENV/bin/python" ]; then
  if ! "$PY" -m venv "$VENV" 2>/dev/null; then
    echo "python3 -m venv thiếu ensurepip, nạp pip từ PyPI (có kiểm tra sha256)..."
    rm -rf "$VENV"
    "$PY" -m venv --without-pip "$VENV"
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    "$PY" -I - "$TMP" <<'PYEOF'
import hashlib, json, sys, urllib.request
meta = json.load(urllib.request.urlopen("https://pypi.org/pypi/pip/json"))
f = next(u for u in meta["urls"] if u["packagetype"] == "bdist_wheel")
data = urllib.request.urlopen(f["url"]).read()
assert hashlib.sha256(data).hexdigest() == f["digests"]["sha256"], "sha256 của pip không khớp"
open(f"{sys.argv[1]}/{f['filename']}", "wb").write(data)
print("pip", meta["info"]["version"], "sha256 ok")
PYEOF
    WHL="$(ls "$TMP"/pip-*.whl)"
    "$VENV/bin/python" "$WHL/pip" install --quiet "$WHL"
  fi
fi

"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$ROOT/backend/requirements-dev.txt"
echo "Backend sẵn sàng: $VENV"
