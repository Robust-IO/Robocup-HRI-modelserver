"""Validate owner_command/v1 semantics without inferring speaker or world position."""

import json


def validate_owner_command(text):
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {'intent', 'region_text', 'ambiguous'}:
        raise ValueError('Expected intent, region_text and ambiguous')
    if value['intent'] not in ('stop', 'arrived', 'unrelated'):
        raise ValueError('intent must be stop, arrived or unrelated')
    if type(value['ambiguous']) is not bool:
        raise ValueError('ambiguous must be boolean')
    region = value['region_text']
    if region is not None:
        if not isinstance(region, str) or not region.strip():
            raise ValueError('region_text must be a nonempty string or null')
        if value['intent'] != 'arrived':
            raise ValueError('Only arrived may include region_text')
        value['region_text'] = region.strip()
    return value
