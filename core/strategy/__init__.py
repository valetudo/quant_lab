"""Strategy abstractions: ABC, Signal/Action/Position dataclasses, lifecycle helpers."""

from core.strategy.base import Strategy
from core.strategy.signals import Action, Position, Signal

__all__ = ["Strategy", "Signal", "Action", "Position"]
