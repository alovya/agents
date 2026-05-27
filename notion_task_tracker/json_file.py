"""JSON file persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json_file(data: dict[str, Any], destination_path: str | Path) -> None:
    destination_path = Path(destination_path)
    destination_path.write_text(
        json.dumps(data, indent=2, sort_keys=True),
        encoding="utf-8",
    )
