"""Typed candidate plans. No generated code, ROS endpoints or physical success claims."""

import json
from .gpsr_command import validate_gpsr_command, command_missing_fields
from .core import identifier, AiError


def exact(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError('Unexpected task-plan fields')


def name(value):
    if not isinstance(value, str):
        raise ValueError('Task-plan identifiers must be strings')
    try:
        identifier(value)
    except AiError as error:
        raise ValueError(str(error)) from error


def plan_inputs(command_json, catalog_json, scene_json):
    command = validate_gpsr_command(command_json)
    if command['ambiguous'] or command_missing_fields(command):
        raise ValueError('Planning requires a complete unambiguous command')
    catalog, scene = json.loads(catalog_json), json.loads(scene_json)
    if not isinstance(catalog, dict) or not catalog:
        raise ValueError('An explicit capability catalog is required')
    for key, capability in catalog.items():
        name(key)
        exact(capability, ('parameters', 'resources', 'completion_predicate'))
        if not isinstance(capability['parameters'], dict):
            raise ValueError('Capability parameters must map names to entity types')
        for parameter, kind in capability['parameters'].items():
            name(parameter)
            name(kind)
        name(capability['completion_predicate'])
        if not isinstance(capability['resources'], list):
            raise ValueError('Capability resources must be a list')
        for resource in capability['resources']:
            name(resource)
    exact(scene, ('entities', 'available_resources'))
    if not isinstance(scene['entities'], dict) or not isinstance(scene['available_resources'], list):
        raise ValueError('Scene requires entities and available resources')
    for key, entity in scene['entities'].items():
        name(key)
        exact(entity, ('type', 'source_id'))
        name(entity['type'])
        name(entity['source_id'])
    for resource in scene['available_resources']:
        name(resource)
    return command, catalog, scene


def validate_candidate(text):
    plan = json.loads(text)
    exact(plan, ('steps', 'uncovered'))
    if not isinstance(plan['steps'], list) or not isinstance(plan['uncovered'], list):
        raise ValueError('Plan steps and uncovered tasks must be lists')
    for task in plan['uncovered']:
        if type(task) is not int or task < 0:
            raise ValueError('Uncovered tasks must be zero-based indices')
    for step in plan['steps']:
        exact(step, ('step_id', 'task_index', 'capability', 'arguments', 'depends_on', 'completion'))
        name(step['step_id'])
        name(step['capability'])
        if type(step['task_index']) is not int or step['task_index'] < 0:
            raise ValueError('Each step requires a command task index')
        if not isinstance(step['arguments'], dict) or not isinstance(step['depends_on'], list):
            raise ValueError('Step requires typed arguments and dependency identifiers')
        for key, value in step['arguments'].items():
            name(key)
            name(value)
        for dependency in step['depends_on']:
            name(dependency)
        exact(step['completion'], ('predicate', 'arguments'))
        name(step['completion']['predicate'])
        if not isinstance(step['completion']['arguments'], dict):
            raise ValueError('Completion requires explicit entity arguments')
    return plan


def validate_plan(plan, command, catalog, scene, task_capabilities):
    """Upper policy is explicit per command task; output is a serial topological order."""
    if not isinstance(task_capabilities, list) or len(task_capabilities) != len(command['tasks']):
        raise ValueError('Parent must bind allowed capabilities for every command task')
    if any(not isinstance(allowed, list) or any(item not in catalog for item in allowed) for allowed in task_capabilities):
        raise ValueError('Task policy must name catalog capabilities')
    steps = {step['step_id']: step for step in plan['steps']}
    if len(steps) != len(plan['steps']):
        raise ValueError('Duplicate plan step identifier')
    covered = set()
    for step in plan['steps']:
        index, capability = step['task_index'], step['capability']
        if index >= len(task_capabilities) or capability not in task_capabilities[index]:
            raise ValueError('Step capability is not authorized for this command task')
        spec = catalog[capability]
        if set(step['arguments']) != set(spec['parameters']):
            raise ValueError('Step arguments do not match capability parameters')
        for key, entity_id in step['arguments'].items():
            if entity_id not in scene['entities'] or scene['entities'][entity_id]['type'] != spec['parameters'][key]:
                raise ValueError('Unknown or incorrectly typed scene entity')
        if any(resource not in scene['available_resources'] for resource in spec['resources']):
            raise ValueError('Required resource is unavailable')
        if step['completion'] != dict(predicate=spec['completion_predicate'], arguments=step['arguments']):
            raise ValueError('Completion predicate/targets do not match capability contract')
        if any(dep not in steps for dep in step['depends_on']):
            raise ValueError('Unknown plan dependency')
        covered.add(index)
    uncovered = set(plan['uncovered'])
    if (len(uncovered) != len(plan['uncovered']) or uncovered & covered
            or covered | uncovered != set(range(len(command['tasks'])))):
        raise ValueError('Every command task must be covered or explicitly uncovered')
    ordered, remaining = [], dict(steps)
    while remaining:
        ready = [key for key, step in remaining.items() if set(step['depends_on']) <= set(ordered)]
        if not ready:
            raise ValueError('Plan dependencies contain a cycle')
        for key in ready:
            ordered.append(key)
            del remaining[key]
    return ordered
