"""Validate spoken order lines; menu, total count and confirmation belong upstairs."""

import json


def validate_restaurant_order(text):
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {'items', 'ambiguous'}:
        raise ValueError('Expected items and ambiguous')
    if type(value['ambiguous']) is not bool or not isinstance(value['items'], list):
        raise ValueError('ambiguous must be boolean and items must be a list')
    for item in value['items']:
        if not isinstance(item, dict) or set(item) != {'name', 'quantity'}:
            raise ValueError('Each item must contain name and quantity')
        name, quantity = item['name'], item['quantity']
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise ValueError('name must be a nonempty string or null')
            item['name'] = name.strip()
        if quantity is not None and (type(quantity) is not int or quantity <= 0):
            raise ValueError('quantity must be a positive integer or null')
    return value


def order_missing_fields(order):
    if not order['items']:
        return ['items']
    return [f'items[{index}].{key}' for index, item in enumerate(order['items'])
            for key in ('name', 'quantity') if item[key] is None]


def menu_aliases(menu):
    """An explicit menu owns aliases; collisions remain visible to the caller."""
    import unicodedata
    from .core import identifier, AiError

    def normalized(value):
        return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
    if not isinstance(menu, list) or not menu:
        raise ValueError('A nonempty menu catalog is required')
    items, aliases = {}, {}
    for item in menu:
        if not isinstance(item, dict) or set(item) != {'menu_item_id', 'name', 'aliases'}:
            raise ValueError('Menu entries require menu_item_id, name and aliases')
        if not isinstance(item['menu_item_id'], str):
            raise ValueError('Menu IDs must be strings')
        try:
            identifier(item['menu_item_id'], 'menu_item_id')
        except (AiError, TypeError) as error:
            raise ValueError('Invalid menu item identifier') from error
        if item['menu_item_id'] in items or not isinstance(item['name'], str) or not item['name'].strip():
            raise ValueError('Menu IDs must be unique and display names nonempty')
        if not isinstance(item['aliases'], list) or any(not isinstance(alias, str) or not alias.strip() for alias in item['aliases']):
            raise ValueError('Menu aliases must be nonempty strings')
        items[item['menu_item_id']] = item
        for alias in [item['menu_item_id'], item['name']] + item['aliases']:
            aliases.setdefault(normalized(alias), set()).add(item['menu_item_id'])
    return items, aliases, normalized


def resolve_order(order, menu):
    items, aliases, normalize = menu_aliases(menu)
    result = dict(items=[], ambiguous=order['ambiguous'])
    for line in order['items']:
        spoken = line['name']
        matches = aliases.get(normalize(spoken), set()) if spoken is not None else set()
        key = next(iter(matches)) if len(matches) == 1 else None
        result['ambiguous'] |= len(matches) > 1
        result['items'].append(dict(menu_item_id=key, name=items[key]['name'] if key else spoken,
                                    spoken_name=spoken, quantity=line['quantity']))
    return result


def validate_order_v2(text):
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {'items', 'ambiguous'}:
        raise ValueError('Expected items and ambiguous')
    if type(value['ambiguous']) is not bool or not isinstance(value['items'], list):
        raise ValueError('Expected item list and boolean ambiguity')
    for item in value['items']:
        if not isinstance(item, dict) or set(item) != {'menu_item_id', 'name', 'spoken_name', 'quantity'}:
            raise ValueError('Expected canonical ID, display name, spoken name and quantity')
        for key in ('menu_item_id', 'name', 'spoken_name'):
            if item[key] is not None and (not isinstance(item[key], str) or not item[key].strip()):
                raise ValueError(key + ' must be a nonempty string or null')
        if item['quantity'] is not None and (type(item['quantity']) is not int or item['quantity'] <= 0):
            raise ValueError('quantity must be a positive integer or null')
    return value


def order_v2_missing_fields(order):
    if not order['items']:
        return ['items']
    return [f'items[{index}].{key}' for index, item in enumerate(order['items'])
            for key in ('menu_item_id', 'quantity') if item[key] is None]


def validate_order_selection(value, menu):
    items, _, _ = menu_aliases(menu)
    for line in value['items']:
        key = line['menu_item_id']
        if key is not None and (key not in items or line['name'] != items[key]['name']):
            raise ValueError('Order ID/display name is not in the current menu')
