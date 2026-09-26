from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ENDPOINT = 'https://data.cityofnewyork.us/resource/erm2-nwe9.json'


def fetch_records(
    start: date,
    end: date,
    limit: int,
    *,
    complaint_type: str | None = None,
    descriptor: str | None = None,
    borough: str | None = None,
    zip_code: str | None = None,
) -> list[dict]:
    if end <= start:
        raise ValueError('End date must be later than start date')
    if not 1 <= limit <= 5000:
        raise ValueError('Limit must be between 1 and 5000')

    days = (end - start).days
    daily_limit, remainder = divmod(limit, days)
    payload = []
    current = start
    while current < end:
        next_day = current + timedelta(days=1)
        day_limit = daily_limit + (1 if (current - start).days < remainder else 0)
        if day_limit:
            where = (
                f'created_date >= "{current.isoformat()}T00:00:00" '
                f'AND created_date < "{next_day.isoformat()}T00:00:00" '
                'AND complaint_type IS NOT NULL '
                'AND borough IS NOT NULL'
            )
            for field, value in (
                ('complaint_type', complaint_type),
                ('descriptor', descriptor),
                ('borough', borough),
                ('incident_zip', zip_code),
            ):
                if value:
                    escaped = value.replace("'", "''")
                    where += f" AND {field} = '{escaped}'"
            params = urlencode({
                '$select': (
                    'unique_key,created_date,complaint_type,descriptor,borough,'
                    'incident_zip,latitude,longitude,agency'
                ),
                '$where': where,
                '$order': 'created_date ASC, unique_key ASC',
                '$limit': str(day_limit),
            })
            request = Request(
                f'{ENDPOINT}?{params}',
                headers={'Accept': 'application/json', 'User-Agent': '311-memory-harness/0.1'},
            )
            with urlopen(request, timeout=60) as response:
                payload.extend(json.load(response))
        current = next_day

    records = []
    for row in payload:
        created = datetime.fromisoformat(row['created_date'].replace('Z', '+00:00'))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        created = created.astimezone(timezone.utc)
        descriptor = row.get('descriptor') or 'Unspecified'
        borough = row.get('borough') or 'Unknown'
        zip_code = row.get('incident_zip') or 'Unknown'
        records.append({
            'id': str(row['unique_key']),
            'text': f"{row['complaint_type']}: {descriptor} reported in {borough} {zip_code}",
            'occurred_at': created.isoformat(),
            'available_at': created.isoformat(),
            'metadata': {
                'complaint_type': row['complaint_type'],
                'descriptor': descriptor,
                'borough': borough,
                'incident_zip': zip_code,
                'location': f'{borough} {zip_code}',
                'latitude': row.get('latitude'),
                'longitude': row.get('longitude'),
                'agency': row.get('agency'),
            },
        })
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description='Fetch a bounded NYC 311 slice from Socrata')
    parser.add_argument('--start', type=date.fromisoformat, required=True, help='Inclusive YYYY-MM-DD')
    parser.add_argument('--end', type=date.fromisoformat, required=True, help='Exclusive YYYY-MM-DD')
    parser.add_argument('--limit', type=int, default=500)
    parser.add_argument('--complaint-type')
    parser.add_argument('--descriptor')
    parser.add_argument('--borough')
    parser.add_argument('--zip')
    parser.add_argument('--output', type=Path, default=Path('fixtures/311-small.json'))
    arguments = parser.parse_args()

    records = fetch_records(
        arguments.start,
        arguments.end,
        arguments.limit,
        complaint_type=arguments.complaint_type,
        descriptor=arguments.descriptor,
        borough=arguments.borough,
        zip_code=arguments.zip,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
    print(f'Wrote {len(records)} records to {arguments.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
