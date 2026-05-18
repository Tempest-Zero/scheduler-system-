"""Tests for converting learned KG patterns into solver constraints (Task 3 -> Task 2)."""
from graphiti_client.resilient_client import patterns_to_constraints


def test_empty_patterns_yield_empty_constraints():
    result = patterns_to_constraints({})
    assert result["avoid_time_slots"] == []
    assert result["prefer_time_slots"] == []


def test_avoided_times_become_penalised_slots():
    result = patterns_to_constraints({"avoided_times": {"gym": [9, 9, 10]}})
    avoid = result["avoid_time_slots"]
    hours = {hour for _, hour, _, _ in avoid}
    assert hours == {9, 10}  # deduplicated
    # Repeated signal (gym avoided 3x) raises the penalty weight.
    assert all(weight > 0 for *_, weight in avoid)


def test_preferred_times_become_negative_weight_bonuses():
    result = patterns_to_constraints({"time_preferences": {"gym": [19]}})
    prefer = result["prefer_time_slots"]
    assert prefer
    assert all(weight < 0 for *_, weight in prefer)


def test_avoid_weight_is_capped():
    # 10 occurrences would exceed the cap; weight must stay bounded.
    result = patterns_to_constraints({"avoided_times": {"gym": [9] * 10}})
    assert all(weight <= 1000 for *_, weight in result["avoid_time_slots"])


def test_weight_is_counted_per_hour_not_per_task():
    # gym avoided once at 09:00 and three times at 22:00 -> the 22:00 slot
    # must carry a stronger penalty than the 09:00 slot.
    result = patterns_to_constraints({"avoided_times": {"gym": [9, 22, 22, 22]}})
    weights = {hour: w for _, hour, _, w in result["avoid_time_slots"]}
    assert weights[22] > weights[9]
