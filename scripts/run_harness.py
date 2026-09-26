from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from backend.contracts import SourceRecord
from backend.harness import HarnessServices, Mode, run_step


def _load_records(path: Path) -> list[SourceRecord]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, list):
        raise ValueError('Input fixture must be a JSON array of source records')
    records = []
    for item in payload:
        record = dict(item)
        record['occurred_at'] = datetime.fromisoformat(record['occurred_at'])
        record['available_at'] = datetime.fromisoformat(record['available_at'])
        records.append(SourceRecord(**record))
    return records


def _load_factory(spec: str) -> Callable[[], HarnessServices]:
    module_name, separator, attribute = spec.partition(':')
    if not separator or not module_name or not attribute:
        raise ValueError('Services factory must use module.path:function_name syntax')
    factory = getattr(importlib.import_module(module_name), attribute)
    if not callable(factory):
        raise TypeError(f'{spec} is not callable')
    return factory


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f'Cannot serialise {type(value).__name__}')


def main() -> int:
    parser = argparse.ArgumentParser(description='Run the 311 memory harness')
    parser.add_argument('--records', required=True, type=Path, help="JSON array of source records, or 'atlas' to read source_records from Atlas")
    parser.add_argument('--services', required=True, help='Services factory as module.path:function_name')
    parser.add_argument('--mode', choices=('baseline', 'memory'), default='memory')
    parser.add_argument('--session-id', default='311-demo')
    parser.add_argument('--batch-size', type=int, default=50)
    arguments = parser.parse_args()
    if arguments.batch_size < 1:
        parser.error('--batch-size must be positive')

    if str(arguments.records) == 'atlas':
        from backend.atlas import connect, load_source_records
        records = load_source_records(connect())
    else:
        records = _load_records(arguments.records)
    services = _load_factory(arguments.services)()
    ordered = sorted(records, key=lambda record: (record.available_at, record.id))
    events = []
    for offset in range(0, len(ordered), arguments.batch_size):
        events.extend(run_step(
            ordered[offset:offset + arguments.batch_size],
            arguments.mode,
            services,
            session_id=arguments.session_id,
        ))
    print(json.dumps([asdict(event) for event in events], default=_json_default, indent=2))
    return int(any(event.type == 'error' for event in events))


if __name__ == '__main__':
    sys.exit(main())
