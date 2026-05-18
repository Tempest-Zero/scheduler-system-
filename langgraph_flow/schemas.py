"""
Pydantic schemas for structured LLM extraction.

IMPORTANT: These schemas are converted to OpenAI function calling specs.
They are NOT embedded in conversation text. This prevents schema leakage.
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field


class TaskSchema(BaseModel):
    """Schema for an extracted task."""
    name: str = Field(description="Task name")
    priority: Literal["high", "medium", "low"] = Field(
        default="medium",
        description="Task priority inferred from urgency/tone"
    )
    estimated_time_hours: Optional[float] = Field(
        default=None,
        description="Estimated duration in hours"
    )
    deadline: Optional[str] = Field(
        default=None,
        description="Deadline in YYYY-MM-DD format"
    )
    difficulty: Literal["hard", "medium", "easy"] = Field(
        default="medium",
        description="Task complexity"
    )
    is_optional: bool = Field(
        default=False,
        description="True if task is explicitly optional or 'if time permits'"
    )
    is_vague: bool = Field(
        default=False,
        description="True if task name is generic or duration unclear"
    )


class FixedSlotSchema(BaseModel):
    """Schema for a fixed time commitment."""
    name: str = Field(description="Commitment name (meeting, class, etc.)")
    start_time: str = Field(description="Start time in HH:MM format")
    end_time: str = Field(description="End time in HH:MM format")


class PreferencesSchema(BaseModel):
    """Schema for user preferences."""
    energy_peak: Literal["morning", "afternoon", "evening"] = Field(
        default="morning",
        description="When user has most energy"
    )
    mood: Literal["high", "normal", "low"] = Field(
        default="normal",
        description="Current mood/energy level"
    )
    work_style: Literal["focused", "balanced", "spread_out"] = Field(
        default="balanced",
        description="Preference for blocked deep work vs spread out tasks"
    )


class ExtractionResultSchema(BaseModel):
    """Complete extraction result schema."""
    is_past_description: bool = Field(
        default=False,
        description="True if user is describing past events, not future tasks"
    )
    wake_time: Optional[str] = Field(
        default=None,
        description="Wake time in HH:MM format"
    )
    sleep_time: Optional[str] = Field(
        default=None,
        description="Sleep/wind-down time in HH:MM format"
    )
    tasks: list[TaskSchema] = Field(
        default_factory=list,
        description="List of extracted tasks"
    )
    fixed_slots: list[FixedSlotSchema] = Field(
        default_factory=list,
        description="Fixed time commitments"
    )
    preferences: PreferencesSchema = Field(
        default_factory=PreferencesSchema,
        description="User preferences"
    )
