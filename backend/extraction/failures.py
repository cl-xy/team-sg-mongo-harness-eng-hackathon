"""Durable replay queue for extraction failures.

This deliberately stores original normalized source records, never a guessed
graph. An operator can feed ``pending()`` back through normal replay once the
model or schema issue is fixed.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .types import ExtractionFailure


class JsonlFailureStore:
    """Append-only local failure store; replace with a collection adapter in Atlas."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __call__(self, failure: ExtractionFailure) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(failure)
        payload["failed_at"] = failure.failed_at.isoformat()
        with self.path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(payload, sort_keys=True) + "\n")

    def pending(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as source:
            return [json.loads(line) for line in source if line.strip()]
