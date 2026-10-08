"""Validation shared by runtime and durable authorization snapshot decoding."""

from collections.abc import Mapping

from rick_authorization import AUTHORIZATION_SNAPSHOT_VERSION, CANONICAL_ROLES, LEGACY_ROLE_ALIASES, canonical_role


SNAPSHOT_FIELDS = (
    "email", "role", "canonical_role", "permissions",
    "authorization_snapshot_version", "authorization_state", "allowed_collection_ids",
)


def bounded_text(value: object, maximum: int) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= maximum
            and not any(ord(char) < 0x20 or ord(char) == 0x7F for char in value))


def text_list(value: object, maximum_items: int, maximum_length: int) -> bool:
    return (isinstance(value, list) and len(value) <= maximum_items
            and all(bounded_text(item, maximum_length) for item in value))


def known_role(value: object) -> bool:
    return (bounded_text(value, 64)
            and (value.strip().upper() in CANONICAL_ROLES or value.strip().lower() in LEGACY_ROLE_ALIASES))


def legacy_snapshot(value: Mapping) -> bool:
    """Only a marked pre-snapshot record or wholly unversioned old row migrates.

    A marker cannot relabel a record already containing modern permissions.
    Version 1 alongside an explicit legacy marker is retained for old imports.
    """
    if "permissions" in value or "canonical_role" in value:
        return False
    if value.get("authorization_state") == "LEGACY_UNMIGRATED":
        version = value.get("authorization_snapshot_version")
        return ("authorization_snapshot_version" not in value
                or (type(version) is int and version == AUTHORIZATION_SNAPSHOT_VERSION))
    return not any(key in value for key in ("authorization_state", "authorization_snapshot_version"))


def valid_authorization_snapshot(value: Mapping) -> bool:
    for name, maximum in (("email", 256), ("role", 64), ("canonical_role", 64)):
        if name in value and not bounded_text(value[name], maximum):
            return False
    if "role" in value and not known_role(value["role"]):
        return False
    if "allowed_collection_ids" in value and not text_list(value["allowed_collection_ids"], 128, 256):
        return False
    if legacy_snapshot(value):
        return True
    version = value.get("authorization_snapshot_version")
    state = value.get("authorization_state")
    role = value.get("canonical_role")
    return (isinstance(state, str) and state in {"AUTHORITATIVE", "MIGRATED"}
            and type(version) is int and version == AUTHORIZATION_SNAPSHOT_VERSION
            and isinstance(role, str) and role in CANONICAL_ROLES
            and ("role" not in value or canonical_role(value["role"]) == role)
            and text_list(value.get("permissions"), 256, 128)
            and text_list(value.get("allowed_collection_ids"), 128, 256))


def snapshot_payload(record: Mapping) -> dict:
    return {key: record[key] for key in SNAPSHOT_FIELDS if key in record}
