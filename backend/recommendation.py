from __future__ import annotations

import json
import urllib.request
from collections.abc import Sequence
from typing import Any

from backend.contracts import RetrievedContext, SourceRecord

OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'
DEFAULT_MODEL = 'anthropic/claude-haiku-4.5'

SYSTEM_PROMPT = (
    'You analyse NYC 311 complaints to find systemic issues that generate repeat complaints. '
    'Recommend one upstream intervention that would eliminate the cluster at its source. '
    'You only see complaint metadata, so any root cause is a hypothesis: say so explicitly and '
    'state what evidence would confirm it. Answer in at most 120 words of plain prose.'
)


def _prompt(
    records: Sequence[SourceRecord], context: RetrievedContext | None, summary: str | None,
) -> str:
    current = '\n'.join(
        f'- {record.occurred_at.date()} {record.text}' for record in records[:40]
    )
    parts = [f'Current batch ({len(records)} complaints):\n{current}']
    if summary:
        parts.append(f'Grouped long-term memory:\n{summary}')
    if context and context.context_text:
        parts.append(f'Retrieved historical memory:\n{context.context_text}')
    return '\n\n'.join(parts)


def call_openrouter(api_key: str, model: str, system: str, user: str, timeout: int = 45) -> str:
    body = json.dumps({
        'model': model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
        'max_tokens': 300,
    }).encode()
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return payload['choices'][0]['message']['content'].strip()


def model_recommendation(
    api_key: str,
    model: str,
    records: Sequence[SourceRecord],
    context: RetrievedContext | None,
    summary: str | None,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    try:
        text = call_openrouter(api_key, model, SYSTEM_PROMPT, _prompt(records, context, summary))
    except Exception as error:
        return {**fallback, 'recommender': 'template', 'model_error': f'{type(error).__name__}: {error}'}
    return {**fallback, 'recommendation': text, 'recommender': model}
