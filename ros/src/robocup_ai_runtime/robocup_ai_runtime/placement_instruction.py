"""Validate placement language; never infer a physical surface or motion permission."""

import json


def validate_placement_instruction(text):
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {'intent', 'region_text', 'surface', 'ambiguous'}:
        raise ValueError('Expected intent, region_text, surface and ambiguous')
    if value['intent'] not in ('place', 'unrelated'):
        raise ValueError('intent must be place or unrelated')
    if value['surface'] not in ('floor', 'non_floor', 'unspecified'):
        raise ValueError('surface must be floor, non_floor or unspecified')
    if type(value['ambiguous']) is not bool:
        raise ValueError('ambiguous must be boolean')
    region = value['region_text']
    if region is not None:
        if not isinstance(region, str) or not region.strip():
            raise ValueError('region_text must be a nonempty string or null')
        value['region_text'] = region.strip()
    if value['intent'] == 'unrelated' and (region is not None or value['surface'] != 'unspecified'):
        raise ValueError('Unrelated speech cannot specify a placement region or surface')
    return value
