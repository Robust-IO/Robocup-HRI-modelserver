"""Language-level readiness, distinct from robot or physical readiness evidence."""

import json


def validate_readiness(text):
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {'status', 'ambiguous'}:
        raise ValueError('Expected status and ambiguous')
    if value['status'] not in ('ready', 'not_ready', 'unknown'):
        raise ValueError('status must be ready, not_ready or unknown')
    if type(value['ambiguous']) is not bool:
        raise ValueError('ambiguous must be boolean')
    return value
