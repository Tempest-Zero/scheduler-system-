"""Tests for scheduler input validation (Pydantic models)."""
from datetime import date

import pytest
from pydantic import ValidationError

from scheduler.models import TaskInput, UserPreferences


def test_task_rejects_sub_15_minute_duration():
    with pytest.raises(ValidationError):
        TaskInput(
            name="Too short",
            priority="low",
            estimated_time_hours=0.1,  # 6 min, below the 0.25h floor
            deadline=date.today(),
        )


def test_task_rejects_unknown_priority():
    with pytest.raises(ValidationError):
        TaskInput(
            name="Bad priority",
            priority="urgent",  # not in {high, medium, low}
            estimated_time_hours=1.0,
            deadline=date.today(),
        )


def test_preferences_have_sensible_defaults():
    prefs = UserPreferences()
    assert prefs.energy_peak == "morning"
    assert prefs.mood == "normal"
    assert prefs.work_style == "balanced"
