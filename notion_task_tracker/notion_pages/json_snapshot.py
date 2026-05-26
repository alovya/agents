"""JSON snapshot persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json_snapshot(snapshot: dict[str, Any], snapshot_path: str | Path) -> None:
    destination_path = Path(snapshot_path)
    destination_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True),
        encoding="utf-8",
    )
