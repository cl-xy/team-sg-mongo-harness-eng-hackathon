from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from backend.contracts import SourceRecord
from backend.harness import HarnessServices, Mode, run_step


def run_endpoint(
    records: Sequence[SourceRecord],
    mode: Mode,
    services: HarnessServices,
    *,
    session_id: str = '311-demo',
) -> dict[str, Any]:
    events = run_step(records, mode, services, session_id=session_id)

    def json_value(value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: json_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [json_value(item) for item in value]
        return value

    return {
        'run_id': events[0].run_id if events else None,
        'simulated_at': events[0].simulated_at.isoformat() if events else None,
        'events': [json_value(asdict(event)) for event in events],
    }
