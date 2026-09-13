#!/usr/bin/env python3
"""Write the API's OpenAPI document to ``web/openapi.json``.

    uv --directory api run python scripts/dump_openapi.py

The Angular client's ``schema.d.ts`` is generated from that file, so this is the
first half of ``npm run api:types`` at the repository root.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api" / "src"))

from eeg_api.main.run import make_app  # noqa: E402


def main() -> int:
    target = ROOT / "web" / "openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Building the app does not start the lifespan, so no hardware is touched here.
    document = make_app().openapi()
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths = document.get("paths", {})
    print(
        f"wrote {target} ({len(paths)} paths, {len(document.get('components', {}).get('schemas', {}))} schemas)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
