"""Sampling omission is distinct from an explicit numeric caller input.

USE_DEFAULT_TEMPERATURE (the default argument) preserves 0.2 on compatible
OpenAI and deterministic providers and uses vendor defaults on native frontier
models and Anthropic. None also requests vendor defaults. Explicit numeric
values are sent unchanged when supported, otherwise rejected before HTTP.
"""
from enum import Enum


class DefaultTemperature(Enum):
    OMITTED = "omitted"


USE_DEFAULT_TEMPERATURE = DefaultTemperature.OMITTED
Temperature = int | float | None | DefaultTemperature
