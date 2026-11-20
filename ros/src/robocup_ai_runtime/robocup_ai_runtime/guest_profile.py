"""Validate the guest_profile/v1 contract; no free-text interpretation here."""

import json


def validate_profile(text):
    """Return a normalized object, including explicit missing and ambiguous fields."""
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {'name', 'drink', 'ambiguous'}:
        raise ValueError('Expected name, drink and ambiguous')
    if type(value['ambiguous']) is not bool:
        raise ValueError('ambiguous must be boolean')
    for key in ('name', 'drink'):
        field = value[key]
        if field is not None:
            if not isinstance(field, str) or not field.strip() or len(field) > 128:
                raise ValueError(f'{key} must be null or a nonempty string of at most 128 chars')
            value[key] = field.strip()
    return value


def validate_profile_v2(text):
    """Receptionist answers plus the parser's confusion score (not ASR confidence)."""
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {'name', 'drink', 'interest', 'ambiguous', 'p'}:
        raise ValueError('Expected name, drink, interest, ambiguous and p')
    base = validate_profile(json.dumps({key: value[key] for key in ('name', 'drink', 'ambiguous')}))
    interest = value['interest']
    if interest is not None:
        if not isinstance(interest, str) or not interest.strip() or len(interest) > 128:
            raise ValueError('interest must be null or a nonempty string of at most 128 chars')
        interest = interest.strip()
    if type(value['p']) is not int or value['p'] < 0:
        raise ValueError('p must be a nonnegative integer')
    return dict(base, interest=interest, p=value['p'])
