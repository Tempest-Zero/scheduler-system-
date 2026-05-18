"""Multi-objective optimization for human-centered scheduling.

Goals:
1. Priority ordering - High priority tasks earlier (but not TOO early)
2. Even distribution - Spread tasks across the day
3. Energy matching - Hard tasks during peak energy
4. Anti-clustering - Avoid bunching tasks together
"""

from ortools.sat.python import cp_model



def build_objective(model, tasks, starts, ends, penalties, day_end, morning_buffer=30, work_style="balanced"):
    """
    Build a balanced objective function that creates human-friendly schedules.
    
    Args:
        work_style: "balanced", "focused", or "spread_out"
    """
    n = len(tasks)
    if n == 0:
        return
    
    priority_weight = {"high": 3, "medium": 2, "low": 1}
    
    # Available scheduling window
    available_window = day_end - morning_buffer
    
    # Collect all terms to minimize
    objective_terms = []
    
    # ==========================================================================
    # COMPONENT 1: Priority-based ordering (scaled down)
    # ==========================================================================
    for i in range(n):
        weight = priority_weight[tasks[i]["priority"]]
        # Scale down by using smaller weights
        scaled_weight = weight
        objective_terms.append(scaled_weight * starts[i])
    
    # ==========================================================================
    # COMPONENT 2: Even distribution across the day
    # ==========================================================================
    # Penalize deviation from ideal evenly-spaced positions
    distribution_weight = 2  # Default for balanced
    if work_style == "focused":
        distribution_weight = 0  # Disable distribution penalty to allow clustering
    elif work_style == "spread_out":
        distribution_weight = 4  # Aggressively enforce spreading

    # Only spread tasks when the day is full enough to need breathing room.
    # On a light day, spreading drifts the first task toward mid-afternoon and
    # leaves a huge empty morning; gating it off lets priority ordering pack
    # tasks soon after wake instead.
    total_duration = sum(t["duration"] for t in tasks)
    fullness_threshold = 0.25 if work_style == "spread_out" else 0.6
    day_is_full = total_duration >= available_window * fullness_threshold

    if n >= 2 and distribution_weight > 0 and day_is_full:
        spacing = available_window // (n + 1)
        
        for i in range(n):
            ideal_position = morning_buffer + (i + 1) * spacing
            
            # Create deviation = |starts[i] - ideal|
            deviation = model.NewIntVar(0, available_window, f"dist_dev_{i}")
            model.AddAbsEquality(deviation, starts[i] - ideal_position)
            
            objective_terms.append(distribution_weight * deviation)
    
    # ==========================================================================
    # COMPONENT 3: Anti-clustering penalty (penalize bunching at start)
    # ==========================================================================
    # Add penalty for tasks starting too early (within first hour after buffer)
    EARLY_THRESHOLD = morning_buffer + 60  # First hour after morning routine
    EARLY_PENALTY = 20
    
    for i in range(n):
        # Create indicator: is this task starting very early?
        too_early = model.NewBoolVar(f"too_early_{i}")
        penalty_var = model.NewIntVar(0, EARLY_PENALTY, f"early_pen_{i}")
        
        model.Add(starts[i] < EARLY_THRESHOLD).OnlyEnforceIf(too_early)
        model.Add(starts[i] >= EARLY_THRESHOLD).OnlyEnforceIf(too_early.Not())
        
        model.Add(penalty_var == EARLY_PENALTY).OnlyEnforceIf(too_early)
        model.Add(penalty_var == 0).OnlyEnforceIf(too_early.Not())
        
        objective_terms.append(penalty_var)
    
    # ==========================================================================
    # COMPONENT 4: External penalties (energy matching, learned constraints)
    # ==========================================================================
    for penalty in penalties:
        objective_terms.append(penalty)
    
    # ==========================================================================
    # COMBINED OBJECTIVE
    # ==========================================================================
    model.Minimize(sum(objective_terms))
