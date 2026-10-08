"""Bounded, offline Draft 2020-12 support for accepted structured output.

This module gates the supported vocabulary; jsonschema owns its semantics.
References, combinators and regexes are deliberately outside this vocabulary.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import NoSuchResource

MAX_SCHEMA_BYTES = 65_536
MAX_SCHEMA_DEPTH = 16
MAX_SCHEMA_NODES = 1_024
MAX_RESULT_DEPTH = 32
MAX_RESULT_NODES = 4_096
MAX_CONTAINER_ITEMS = 256
DIALECT = 'https://json-schema.org/draft/2020-12/schema'
KEYWORDS = frozenset({
    '$schema', 'title', 'description', 'default', 'examples', 'deprecated', 'readOnly', 'writeOnly',
    'type', 'enum', 'const', 'properties', 'required', 'additionalProperties',
    'items', 'prefixItems', 'minItems', 'maxItems', 'uniqueItems',
    'minProperties', 'maxProperties', 'minLength', 'maxLength',
    'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf',
})

def _deny_retrieval(uri):
    raise NoSuchResource(ref=uri)

OFFLINE_REGISTRY = Registry(retrieve=_deny_retrieval)

def bounded_value(value, *, depth=MAX_RESULT_DEPTH, nodes=MAX_RESULT_NODES):
    """Bound acyclic JSON trees before recursive parsing/validator traversal."""
    pending, count = [(value, 0)], 0
    while pending:
        item, level = pending.pop()
        count += 1
        if level > depth or count > nodes:
            raise ValueError('structured value exceeds tree limits')
        if isinstance(item, Mapping):
            if len(item) > MAX_CONTAINER_ITEMS or any(not isinstance(k, str) for k in item):
                raise ValueError('invalid structured object')
            pending.extend((v, level + 1) for v in item.values())
        elif isinstance(item, list):
            if len(item) > MAX_CONTAINER_ITEMS:
                raise ValueError('structured array exceeds limit')
            pending.extend((v, level + 1) for v in item)
        elif type(item) is float and not math.isfinite(item):
            raise ValueError('nonfinite structured number')
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValueError('invalid structured scalar')

def schema_validator(schema):
    """Reject unsupported configuration before any provider I/O."""
    bounded_value(schema, depth=MAX_SCHEMA_DEPTH, nodes=MAX_SCHEMA_NODES)
    if len(json.dumps(schema, allow_nan=False).encode('utf-8')) > MAX_SCHEMA_BYTES:
        raise ValueError('schema exceeds byte limit')
    pending = [schema]
    while pending:
        node = pending.pop()
        if type(node) is bool:
            continue
        if not isinstance(node, Mapping) or set(node) - KEYWORDS:
            raise ValueError('unsupported schema vocabulary')
        if '$schema' in node and node['$schema'] != DIALECT:
            raise ValueError('unsupported schema dialect')
        if 'properties' in node:
            if not isinstance(node['properties'], Mapping):
                raise ValueError('invalid properties')
            pending.extend(node['properties'].values())
        for key in ('items', 'additionalProperties'):
            if key in node:
                pending.append(node[key])
        if 'prefixItems' in node:
            if not isinstance(node['prefixItems'], list):
                raise ValueError('invalid prefixItems')
            pending.extend(node['prefixItems'])
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=OFFLINE_REGISTRY)

def validate_instance(schema, value):
    bounded_value(value)
    schema_validator(schema).validate(value)

SCHEMA_FAILURES = (TypeError, ValueError, OverflowError, RecursionError, SchemaError)
RESULT_FAILURES = (TypeError, ValueError, ArithmeticError, RecursionError, ValidationError, SchemaError)
