"""Explicit documented alias relationships, without live model resolution."""
from datetime import datetime
import re

def matches_model(requested: str, actual: str, *, native_openai=False, anthropic=False) -> bool:
    if actual == requested:
        return True
    # Only the snapshot listed by the official GPT-4o Mini model page.
    if native_openai and requested == 'gpt-4o-mini':
        return actual == 'gpt-4o-mini-2024-07-18'
    # Before 4.6, native aliases resolve within the same minor version.
    # Restrict this implementation to the explicitly documented 4.5 families.
    if anthropic and requested in {'claude-sonnet-4-5', 'claude-haiku-4-5'}:
        if not re.fullmatch(re.escape(requested) + r'-[0-9]{8}', actual):
            return False
        try:
            datetime.strptime(actual[-8:], '%Y%m%d')
        except ValueError:
            return False
        return True
    return False
