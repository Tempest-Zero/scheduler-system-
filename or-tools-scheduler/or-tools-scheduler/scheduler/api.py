"""Public API for the scheduler."""

from .solver import generate_schedule
from .models import (
    ScheduleRequest,
    ScheduleResponse,
    ScheduledBlock,
    TaskInput,
    FixedSlot,
    UserPreferences,
)

__all__ = [
    "generate_schedule",
    "ScheduleRequest",
    "ScheduleResponse",
    "ScheduledBlock",
    "TaskInput",
    "FixedSlot",
    "UserPreferences",
]
