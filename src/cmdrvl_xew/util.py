from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    """UTC timestamp in ISO 8601 format with 'Z' suffix and no fractional seconds."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            n += len(chunk)
            h.update(chunk)
    return h.hexdigest(), n


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Deterministic-ish formatting for diffs and reproducibility.
    data = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True)
    path.write_text(data + "\n", encoding="utf-8")


@dataclass(frozen=True)
class FileHash:
    path: str
    sha256: str
    bytes: int
