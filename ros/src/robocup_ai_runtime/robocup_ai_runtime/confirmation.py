"""Validate confirmation language, without attributing identity or authorization."""

import json


def validate_confirmation(text):
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {'decision', 'ambiguous'}:
        raise ValueError('Expected decision and ambiguous')
    if value['decision'] not in ('yes', 'no', 'unknown'):
        raise ValueError('decision must be yes, no or unknown')
    if type(value['ambiguous']) is not bool:
        raise ValueError('ambiguous must be boolean')
    return value
