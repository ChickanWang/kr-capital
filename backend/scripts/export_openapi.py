"""Write the API's OpenAPI spec to backend/openapi.json (the frontend generates TS types from it).
CI fails if the committed file is out of date."""

import json
from pathlib import Path

from app.api.main import app

path = Path(__file__).resolve().parents[1] / "openapi.json"
path.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
print(f"wrote {path}")
