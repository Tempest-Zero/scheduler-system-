"""Pydantic models for type-safe scheduler API."""

from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import date


class TaskInput(BaseModel):
    """A task to be scheduled."""
    name: str
    priority: Literal["high", "medium", "low"]
    estimated_time_hours: float = Field(ge=0.25)  # Min 15 minutes
    deadline: date
    difficulty: Literal["hard", "medium", "easy"] = "medium"
    category: Optional[str] = None
    is_optional: bool = False


class FixedSlot(BaseModel):
    """A fixed time block (e.g., class, meeting)."""
    name: str
    start_time: str  # "HH:MM"
    end_time: str    # "HH:MM"


class UserPreferences(BaseModel):
    """User preferences for scheduling."""
    energy_peak: Literal["morning", "afternoon", "evening"] = "morning"
    mood: Literal["high", "normal", "low"] = "normal"
    work_style: Literal["focused", "balanced", "spread_out"] = "balanced"
    focus_duration_preference: int = 90   # minutes
    break_duration_preference: int = 15   # minutes


class ScheduleRequest(BaseModel):
    """Input to the scheduler."""
    tasks: list[TaskInput]
    fixed_slots: list[FixedSlot] = []
    preferences: UserPreferences = UserPreferences()
    day_start_time: str = "09:00"
    day_end_time: str = "22:00"
    date: date


class ScheduledBlock(BaseModel):
    """A single scheduled task block."""
    task_name: str
    start_time: str
    end_time: str
    reason: str


class ScheduleResponse(BaseModel):
    """Output from the scheduler."""
    status: Literal["optimal", "feasible", "infeasible", "partial"]
    schedule: list[ScheduledBlock] = []
    overflow_tasks: list[str] = []  # Tasks that couldn't fit
    error: Optional[str] = None

