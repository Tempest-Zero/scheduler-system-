"""Tests for the OR-Tools schedule solver (Task 2)."""
from datetime import date

import pytest

from scheduler.solver import generate_schedule, _auto_insert_lunch
from scheduler.models import ScheduleRequest, TaskInput, FixedSlot, UserPreferences
from scheduler.utils import time_to_minutes


def _task(name, hours, priority="medium", difficulty="medium"):
    return TaskInput(
        name=name,
        priority=priority,
        estimated_time_hours=hours,
        deadline=date.today(),
        difficulty=difficulty,
    )


def _request(tasks, fixed_slots=None, start="09:00", end="18:00"):
    return ScheduleRequest(
        tasks=tasks,
        fixed_slots=fixed_slots or [],
        preferences=UserPreferences(),
        day_start_time=start,
        day_end_time=end,
        date=date.today(),
    )


def test_solves_simple_schedule():
    resp = generate_schedule(_request([_task("Report", 2.0), _task("Emails", 0.5)]))
    assert resp.status in ("optimal", "feasible")
    assert resp.schedule
    scheduled = {b.task_name for b in resp.schedule}
    assert "Report" in scheduled and "Emails" in scheduled


def test_blocks_never_overlap():
    resp = generate_schedule(_request([_task("A", 1.0), _task("B", 1.5), _task("C", 0.75)]))
    blocks = sorted(resp.schedule, key=lambda b: time_to_minutes(b.start_time))
    for earlier, later in zip(blocks, blocks[1:]):
        assert time_to_minutes(earlier.end_time) <= time_to_minutes(later.start_time)


def test_overflow_tasks_pushed_when_day_too_short():
    # ~30h of work cannot fit a 9h day -> some tasks overflow.
    tasks = [_task(f"T{i}", 4.0) for i in range(8)]
    resp = generate_schedule(_request(tasks))
    assert resp.status == "partial"
    assert resp.overflow_tasks


def test_overlapping_fixed_slots_are_rejected():
    slots = [
        FixedSlot(name="Standup", start_time="10:00", end_time="11:00"),
        FixedSlot(name="Review", start_time="10:30", end_time="11:30"),
    ]
    resp = generate_schedule(_request([_task("Report", 1.0)], fixed_slots=slots))
    assert resp.status == "infeasible"
    assert "overlap" in (resp.error or "").lower()


def test_lunch_auto_inserted_when_day_spans_noon():
    req = _request([_task("Report", 2.0)], start="09:00", end="18:00")
    assert not req.fixed_slots
    _auto_insert_lunch(req)
    assert any("lunch" in s.name.lower() for s in req.fixed_slots)


def test_lunch_not_inserted_when_day_ends_before_noon():
    req = _request([_task("Report", 1.0)], start="06:00", end="11:00")
    _auto_insert_lunch(req)
    assert not any("lunch" in s.name.lower() for s in req.fixed_slots)


def test_fixed_slot_is_respected():
    slots = [FixedSlot(name="Standup", start_time="10:00", end_time="10:30")]
    resp = generate_schedule(_request([_task("Report", 1.0)], fixed_slots=slots))
    for block in resp.schedule:
        if block.task_name == "Report":
            start = time_to_minutes(block.start_time)
            end = time_to_minutes(block.end_time)
            # Must not overlap the 10:00-10:30 standup.
            assert end <= 600 or start >= 630


def test_empty_task_list_does_not_crash():
    resp = generate_schedule(_request([]))
    assert resp.status in ("optimal", "feasible")
