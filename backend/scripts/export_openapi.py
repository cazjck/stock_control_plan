"""Xuất OpenAPI ra backend/openapi.json để frontend sinh kiểu TypeScript (npm run gen:api)."""
import json
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("BROKERS", "demo")

from app.main import create_app  # noqa: E402

out = Path(__file__).resolve().parents[1] / "openapi.json"
out.write_text(json.dumps(create_app().openapi(), ensure_ascii=False, indent=1))
print("wrote", out)
