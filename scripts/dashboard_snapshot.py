"""Export measured dashboard data from the existing deterministic harness."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from backend.contracts import SourceRecord
from backend.harness import run_step
from backend.runtime import create_services
from scripts.run_harness import _json_default, _load_records


def build_snapshot(records: list[SourceRecord], batch_size: int = 20) -> dict:
    if batch_size < 1:
        raise ValueError('batch_size must be positive')
    if not records:
        raise ValueError('Replay needs at least one source record')
    ordered = sorted(records, key=lambda item: (item.available_at, item.id))
    memory, baseline = create_services(), create_services()
    batches = []
    for offset in range(0, len(ordered), batch_size):
        batch = ordered[offset:offset + batch_size]
        memory_events = run_step(batch, 'memory', memory)
        baseline_events = run_step(batch, 'baseline', baseline)
        errors = [event for event in memory_events + baseline_events if event.type == 'error']
        if errors:
            raise RuntimeError(errors[0].payload['error_description'])
        batches.append({
            'number': len(batches) + 1,
            'as_of': max(record.available_at for record in batch).isoformat(),
            'record_ids': [record.id for record in batch],
            'events': [asdict(event) for event in memory_events],
            'node_count': len(memory.nodes),
            'edge_count': len(memory.edges),
        })

    def response(events):
        payload = next(event.payload for event in events if event.type == 'recommended')
        return {
            'text': payload['recommendation'],
            'current_source_ids': payload['evidence_source_ids'],
            'historical_source_ids': payload['historical_context_source_ids'],
            'latency_ms': None,
            'input_tokens': None,
            'output_tokens': None,
        }

    retrieval = next(event.payload for event in memory_events if event.type == 'retrieved')
    result = {
        'mode': 'replay',
        'generated_at': datetime.now(timezone.utc),
        'adapter': 'Deterministic in-memory harness',
        'record_count': len(ordered),
        'batch_size': batch_size,
        'batches': batches,
        'records': [asdict(record) for record in ordered],
        'nodes': [asdict(node) for node in memory.nodes.values()],
        'edges': [asdict(edge) for edge in memory.edges.values()],
        'baseline': response(baseline_events),
        'memory': response(memory_events),
        'context': {**retrieval, 'context_text': '', 'nodes': [], 'edges': []},
        'prompt': 'What recurring issue should we investigate in the latest complaint batch?',
    }
    return json.loads(json.dumps(result, default=_json_default))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=Path, default=Path('fixtures/311-small.json'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = json.dumps(build_snapshot(_load_records(args.records)), indent=2)
    if args.output:
        args.output.write_text(output + '\n')
    else:
        print(output)


if __name__ == '__main__':
    main()
