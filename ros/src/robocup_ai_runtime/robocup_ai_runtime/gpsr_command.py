"""Spoken goals and explicit subtasks; no generated steps, ROS endpoints or plan."""

import json


SLOTS = ('action_text', 'object_text', 'person_text', 'source_text', 'destination_text')


def validate_gpsr_command(text):
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {'goal_text', 'tasks', 'ambiguous'}:
        raise ValueError('Expected goal_text, tasks and ambiguous')
    if type(value['ambiguous']) is not bool or not isinstance(value['tasks'], list):
        raise ValueError('ambiguous must be boolean and tasks must be a list')
    goal = value['goal_text']
    if goal is not None:
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError('goal_text must be a nonempty string or null')
        value['goal_text'] = goal.strip()
    for task in value['tasks']:
        if not isinstance(task, dict) or set(task) != set(SLOTS) | {'conditions', 'missing_fields'}:
            raise ValueError('Each task must contain the five text slots, conditions and missing_fields')
        for key in SLOTS:
            field = task[key]
            if field is not None:
                if not isinstance(field, str) or not field.strip():
                    raise ValueError(key + ' must be a nonempty string or null')
                task[key] = field.strip()
        if not isinstance(task['conditions'], list):
            raise ValueError('conditions must be a list of explicit text conditions')
        for index, condition in enumerate(task['conditions']):
            if not isinstance(condition, str) or not condition.strip():
                raise ValueError('Each condition must be a nonempty string')
            task['conditions'][index] = condition.strip()
        missing = task['missing_fields']
        if not isinstance(missing, list):
            raise ValueError('missing_fields must be a list of absent required slot names')
        for key in missing:
            if key not in SLOTS or task[key] is not None:
                raise ValueError('missing_fields must reference a null text slot')
    return value


def command_missing_fields(command):
    missing = ['goal_text'] if command['goal_text'] is None else []
    if not command['tasks']:
        missing.append('tasks')
    for index, task in enumerate(command['tasks']):
        keys = list(task['missing_fields'])
        if task['action_text'] is None and 'action_text' not in keys:
            keys.insert(0, 'action_text')
        missing.extend(f'tasks[{index}].{key}' for key in keys)
    return missing
