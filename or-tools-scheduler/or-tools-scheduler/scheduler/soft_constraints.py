"""Soft constraints for schedule optimization."""

from ortools.sat.python import cp_model


ENERGY_PEAK_HOURS = {
    "morning": (6, 11),
    "afternoon": (12, 16),
    "evening": (17, 21),
}

PRIORITY_WEIGHT = {"high": 300, "medium": 100, "low": 30}
DIFFICULTY_WEIGHT = {"hard": 200, "medium": 50, "easy": 0}


def build_soft_penalties(
    model: cp_model.CpModel,
    tasks: list[dict],
    starts: list,
    preferences,
    day_start: int,
) -> list:
    """
    Build soft constraint penalties for the objective function.
    
    Penalties:
    1. Energy matching - hard tasks outside peak hours
    2. Priority weighting - high priority tasks scheduled late
    """
    penalties = []
    
    # 1. Energy matching
    peak_start, peak_end = ENERGY_PEAK_HOURS[preferences.energy_peak]
    # FIX: Clamp peak times to valid day range [0, 840] to avoid impossible constraints
    DAY_END_MAX = 840  # 14 hours max day
    peak_start_mins = max(0, (peak_start * 60) - day_start)
    peak_end_mins = min((peak_end * 60) - day_start, DAY_END_MAX)
    
    # Skip energy matching if peak hours are entirely outside the day window
    if peak_end_mins <= 0:
        # Peak is before the day starts
        return penalties
    if peak_start_mins >= DAY_END_MAX:
        # Peak is after the day ends
        return penalties
    
    for i, task in enumerate(tasks):
        if task.get("difficulty") == "hard":
            outside_penalty = model.NewIntVar(0, 1000, f"energy_penalty_{i}")
            
            in_peak = model.NewBoolVar(f"in_peak_{i}")
            
            # in_peak = True if start is within peak hours
            # FIX: Use proper reification that doesn't create impossible constraints
            model.Add(starts[i] >= peak_start_mins).OnlyEnforceIf(in_peak)
            model.Add(starts[i] < peak_end_mins).OnlyEnforceIf(in_peak)
            
            # For in_peak.Not(), we need: start < peak_start OR start >= peak_end
            # Instead of creating impossible constraints, just check against valid range
            before_peak = model.NewBoolVar(f"before_peak_{i}")
            after_peak = model.NewBoolVar(f"after_peak_{i}")
            
            if peak_start_mins > 0:
                model.Add(starts[i] < peak_start_mins).OnlyEnforceIf(before_peak)
                model.Add(starts[i] >= peak_start_mins).OnlyEnforceIf(before_peak.Not())
            else:
                model.Add(before_peak == 0)  # Can't be before peak if peak starts at 0
            
            model.Add(starts[i] >= peak_end_mins).OnlyEnforceIf(after_peak)
            model.Add(starts[i] < peak_end_mins).OnlyEnforceIf(after_peak.Not())
            
            # in_peak.Not() means before_peak OR after_peak
            model.AddBoolOr([before_peak, after_peak]).OnlyEnforceIf(in_peak.Not())
            model.AddBoolAnd([before_peak.Not(), after_peak.Not()]).OnlyEnforceIf(in_peak)
            
            model.Add(outside_penalty == 0).OnlyEnforceIf(in_peak)
            model.Add(outside_penalty == DIFFICULTY_WEIGHT["hard"]).OnlyEnforceIf(in_peak.Not())
            
            penalties.append(outside_penalty)
    
    return penalties


def apply_mood_adjustment(tasks: list[dict], mood: str) -> None:
    """Adjust task durations based on mood (in-place)."""
    multiplier = {"high": 0.9, "normal": 1.0, "low": 1.2}[mood]
    for task in tasks:
        task["duration"] = int(task["duration"] * multiplier)


def add_learned_constraints(
    model: cp_model.CpModel,
    tasks: list[dict],
    starts: list,
    ends: list,
    learned_constraints: dict,
    day_start: int,
) -> list:
    """
    Apply learned time preferences and avoidances.
    
    Uses proper two-way channeling to avoid forced boolean values.
    """
    penalties = []
    
    if not learned_constraints:
        return penalties
    
    DAY_END_MAX = 840  # 14 hours max
    
    # Avoidance penalties
    for task_pattern, start_hour, end_hour, weight in learned_constraints.get("avoid_time_slots", []):
        # CLAMP to valid range
        avoid_start = max(0, (start_hour * 60) - day_start)
        avoid_end = min((end_hour * 60) - day_start, DAY_END_MAX)
        
        # Skip if window is entirely outside day
        if avoid_end <= 0 or avoid_start >= DAY_END_MAX:
            continue
        
        # Skip if window is invalid (start >= end after clamping)
        if avoid_start >= avoid_end:
            continue
        
        for i, task in enumerate(tasks):
            if task_pattern.lower() not in task["name"].lower():
                continue
            
            # Create penalty variable with tight bounds
            penalty = model.NewIntVar(0, abs(weight), f"avoid_{task_pattern}_{i}")
            
            # Boolean: is task in avoided window?
            in_avoided = model.NewBoolVar(f"in_avoided_{task_pattern}_{i}")
            
            # Two-way channeling with helper booleans
            before_avoid = model.NewBoolVar(f"before_avoid_{task_pattern}_{i}")
            after_avoid = model.NewBoolVar(f"after_avoid_{task_pattern}_{i}")
            
            # before_avoid ↔ (start < avoid_start)
            if avoid_start > 0:
                model.Add(starts[i] < avoid_start).OnlyEnforceIf(before_avoid)
                model.Add(starts[i] >= avoid_start).OnlyEnforceIf(before_avoid.Not())
            else:
                # Can't be before if avoid_start is 0
                model.Add(before_avoid == 0)
            
            # after_avoid ↔ (start >= avoid_end)
            model.Add(starts[i] >= avoid_end).OnlyEnforceIf(after_avoid)
            model.Add(starts[i] < avoid_end).OnlyEnforceIf(after_avoid.Not())
            
            # in_avoided → (start >= avoid_start AND start < avoid_end)
            model.Add(starts[i] >= avoid_start).OnlyEnforceIf(in_avoided)
            model.Add(starts[i] < avoid_end).OnlyEnforceIf(in_avoided)
            
            # NOT in_avoided ↔ (before_avoid OR after_avoid)
            model.AddBoolOr([before_avoid, after_avoid]).OnlyEnforceIf(in_avoided.Not())
            model.AddBoolAnd([before_avoid.Not(), after_avoid.Not()]).OnlyEnforceIf(in_avoided)
            
            # Penalty assignment
            model.Add(penalty == abs(weight)).OnlyEnforceIf(in_avoided)
            model.Add(penalty == 0).OnlyEnforceIf(in_avoided.Not())
            
            penalties.append(penalty)
    
    # Preference bonuses (negative weight = reward)
    for task_pattern, start_hour, end_hour, weight in learned_constraints.get("prefer_time_slots", []):
        # CLAMP to valid range
        prefer_start = max(0, (start_hour * 60) - day_start)
        prefer_end = min((end_hour * 60) - day_start, DAY_END_MAX)
        
        # Skip if window is invalid
        if prefer_end <= 0 or prefer_start >= DAY_END_MAX:
            continue
        if prefer_start >= prefer_end:
            continue
        
        for i, task in enumerate(tasks):
            if task_pattern.lower() not in task["name"].lower():
                continue
            
            # Bonus variable (negative values reduce objective)
            bonus = model.NewIntVar(weight, 0, f"prefer_{task_pattern}_{i}")
            
            in_preferred = model.NewBoolVar(f"in_preferred_{task_pattern}_{i}")
            
            # Two-way channeling
            before_prefer = model.NewBoolVar(f"before_prefer_{task_pattern}_{i}")
            after_prefer = model.NewBoolVar(f"after_prefer_{task_pattern}_{i}")
            
            if prefer_start > 0:
                model.Add(starts[i] < prefer_start).OnlyEnforceIf(before_prefer)
                model.Add(starts[i] >= prefer_start).OnlyEnforceIf(before_prefer.Not())
            else:
                model.Add(before_prefer == 0)
            
            model.Add(starts[i] >= prefer_end).OnlyEnforceIf(after_prefer)
            model.Add(starts[i] < prefer_end).OnlyEnforceIf(after_prefer.Not())
            
            model.Add(starts[i] >= prefer_start).OnlyEnforceIf(in_preferred)
            model.Add(starts[i] < prefer_end).OnlyEnforceIf(in_preferred)
            
            model.AddBoolOr([before_prefer, after_prefer]).OnlyEnforceIf(in_preferred.Not())
            model.AddBoolAnd([before_prefer.Not(), after_prefer.Not()]).OnlyEnforceIf(in_preferred)
            
            model.Add(bonus == weight).OnlyEnforceIf(in_preferred)
            model.Add(bonus == 0).OnlyEnforceIf(in_preferred.Not())
            
            penalties.append(bonus)
    
    return penalties

