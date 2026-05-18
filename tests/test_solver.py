"""Tests for the OR-Tools schedule solver (Task 2)."""
from datetime import date

import pytest

from scheduler.solver import (
    generate_schedule,
    _auto_insert_lunch,
    MAX_MORNING_ROUTINE_MINUTES,
    MAX_BREAK_MINUTES,
)
from scheduler.models import ScheduleRequest, TaskInput, FixedSlot, UserPreferences
from scheduler.utils import time_to_minutes

# Injected filler blocks (routine / open time / breaks) vs. real task blocks.
_FILLER_KEYWORDS = ("Routine", "Open Time", "Break")


def _is_filler(block):
    return any(kw in block.task_name for kw in _FILLER_KEYWORDS)


def _duration(block):
    return time_to_minutes(block.end_time) - time_to_minutes(block.start_time)


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
    # Eight 1h tasks (inflated well past a 9h day) -> some fit, some overflow.
    tasks = [_task(f"T{i}", 1.0) for i in range(8)]
    resp = generate_schedule(_request(tasks))
    assert resp.status == "partial"
    assert resp.overflow_tasks
    # The tasks that did fit are still scheduled.
    assert any(not _is_filler(b) for b in resp.schedule)


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


def test_morning_routine_block_is_capped():
    # A 2h task cannot fit before the auto-inserted noon lunch, so it lands
    # in the afternoon -- the morning gap must not become a giant routine block.
    resp = generate_schedule(_request([_task("Report", 2.0, "high", "hard")]))
    routines = [b for b in resp.schedule if "Routine" in b.task_name]
    assert routines
    for block in routines:
        assert _duration(block) <= MAX_MORNING_ROUTINE_MINUTES


def test_break_blocks_are_capped():
    resp = generate_schedule(
        _request([_task("Report", 2.0, "high", "hard"), _task("Emails", 0.5, "low", "easy")])
    )
    breaks = [b for b in resp.schedule if "Break" in b.task_name]
    for block in breaks:
        assert _duration(block) <= MAX_BREAK_MINUTES


def test_first_task_starts_soon_after_wake_on_light_day():
    # On a light day the first real task should start near the morning buffer,
    # not drift into the afternoon.
    resp = generate_schedule(
        _request([_task("Report", 2.0, "high", "hard"), _task("Emails", 0.5, "low", "easy")])
    )
    real = [b for b in resp.schedule if not _is_filler(b)]
    assert real
    first_start = time_to_minutes(real[0].start_time)
    assert first_start - time_to_minutes("09:00") <= 60


def test_oversized_single_task_is_infeasible_not_partial():
    # A task far longer than the day cannot be scheduled; the result must be
    # an honest "infeasible", never a "partial" with an empty schedule.
    resp = generate_schedule(_request([_task("Marathon", 12.0, "high", "hard")]))
    assert resp.status == "infeasible"
    assert not [b for b in resp.schedule if not _is_filler(b)]


def test_partial_schedule_actually_places_kept_tasks():
    # Many tasks: the day overflows, but whatever is kept must really solve.
    tasks = [_task(f"T{i}", 1.0) for i in range(10)]
    resp = generate_schedule(_request(tasks))
    assert resp.status in ("partial", "infeasible")
    if resp.status == "partial":
        kept = {b.task_name for b in resp.schedule if not _is_filler(b)}
        assert kept and kept.isdisjoint(set(resp.overflow_tasks))


def test_busy_day_still_spreads_tasks():
    # Six short tasks fill the day -- the schedule should span into the
    # afternoon rather than bunching everything into the morning.
    tasks = [_task(f"T{i}", 0.5) for i in range(6)]
    resp = generate_schedule(_request(tasks))
    assert resp.status in ("optimal", "feasible")
    real = [b for b in resp.schedule if not _is_filler(b)]
    assert len(real) == 6
    last_end = max(time_to_minutes(b.end_time) for b in real)
    assert last_end - time_to_minutes("09:00") >= 5 * 60
