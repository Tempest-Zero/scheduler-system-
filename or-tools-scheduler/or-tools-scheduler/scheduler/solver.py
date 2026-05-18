"""OR-Tools constraint satisfaction scheduler with human-centered optimization."""

from ortools.sat.python import cp_model
from datetime import date

from .models import (
    ScheduleRequest,
    ScheduleResponse,
    ScheduledBlock,
    FixedSlot,
)
from .constraint import add_task_constraints, MORNING_BUFFER_MINUTES
from .objective import build_objective
from .soft_constraints import build_soft_penalties, apply_mood_adjustment, add_learned_constraints
from .utils import time_to_minutes, minutes_to_time

# =============================================================================
# SCHEDULING CONSTANTS - Human-Centered Defaults
# =============================================================================

# Morning routine buffer - no tasks in first N minutes after wake
MORNING_BUFFER_MINUTES = 30

# Buffer between tasks for context switching
BUFFER_MINUTES = 15

# Realism factor - tasks typically take 20% longer than estimated
REALISM_FACTOR = 1.2

# Deep work constraints
MAX_DEEP_WORK_BLOCKS = 2  # Max 2x deep work sessions per day
DEEP_WORK_DURATION = 90   # Each deep work block is 90 minutes

# Context switching - mandatory break after N minutes of work
FOCUS_BLOCK_DURATION = 50  # Work for 50 minutes
CONTEXT_SWITCH_BREAK = 10  # Then 10 minute break

# Shutdown time - how many minutes before day end to stop scheduling
SHUTDOWN_BUFFER = 60  # Stop scheduling 1 hour before day end

# Filler-block caps - a wake-to-first-task or between-task gap longer than
# these is split so the surplus shows as honest "Open Time" rather than an
# absurdly long routine/break block.
MAX_MORNING_ROUTINE_MINUTES = 45
MAX_BREAK_MINUTES = 90


def _realistic_duration(estimated_hours: float) -> int:
    """Minutes a task occupies before mood adjustment.

    Single source of truth for the realism factor + context-switch buffer, so
    the feasibility pre-check and the solver agree on how much time a task
    really costs.
    """
    raw = int(estimated_hours * 60)
    return int(raw * REALISM_FACTOR) + BUFFER_MINUTES


def generate_schedule(request: ScheduleRequest, learned_constraints: dict = None) -> ScheduleResponse:
    """
    Generate an optimized schedule from the request.

    Tries to schedule every task. If the day is over-constrained, the
    least-important tasks (latest deadline, lowest priority) are dropped one
    at a time until a schedule is found, and reported as overflow. The solver
    itself is the source of truth for feasibility - a static capacity estimate
    cannot account for fragmentation by fixed slots, deadlines or buffers.

    Args:
        request: ScheduleRequest with tasks, fixed slots, and preferences
        learned_constraints: Optional dict with avoid_time_slots and prefer_time_slots
            from user edit history

    Returns:
        ScheduleResponse with status and scheduled blocks
    """
    # Auto-insert lunch if window spans noon
    _auto_insert_lunch(request)

    # Parse day boundaries
    day_start = time_to_minutes(request.day_start_time)
    day_end = time_to_minutes(request.day_end_time)
    DAY_END = day_end - day_start

    # First attempt: schedule the full task set.
    result = _solve_schedule(request, day_start, DAY_END, learned_constraints)
    if result.status in ("optimal", "feasible"):
        return result

    # Over-constrained: drop the least-important task and retry until it fits.
    ordered = sorted(
        request.tasks,
        key=lambda t: (t.deadline, {"high": 0, "medium": 1, "low": 2}[t.priority]),
    )
    overflow = []

    while len(ordered) > 1:
        overflow.insert(0, ordered.pop())  # remove least-important task
        partial_request = ScheduleRequest(
            tasks=list(ordered),
            fixed_slots=request.fixed_slots,
            preferences=request.preferences,
            day_start_time=request.day_start_time,
            day_end_time=request.day_end_time,
            date=request.date,
        )
        result = _solve_schedule(partial_request, day_start, DAY_END, learned_constraints)
        if result.status in ("optimal", "feasible"):
            result.status = "partial"
            result.overflow_tasks = [t.name for t in overflow]
            result.error = f"Moved {len(overflow)} task(s) to tomorrow due to time constraints"
            return result

    # Not even a single task fits - return the honest infeasible result.
    return result


def _solve_schedule(request: ScheduleRequest, day_start: int, DAY_END: int, learned_constraints: dict = None) -> ScheduleResponse:
    """Core solver logic with human-centered constraints."""
    
    # Effective day end (apply shutdown buffer - no tasks in last hour)
    effective_day_end = DAY_END - SHUTDOWN_BUFFER
    
    # Convert tasks to internal format
    tasks = []
    for task in request.tasks:
        days_until = (task.deadline - request.date).days
        deadline_minutes = min((days_until + 1) * effective_day_end, effective_day_end)
        
        # Apply 20% realism factor - tasks take longer than estimated
        raw_duration = int(task.estimated_time_hours * 60)
        realistic_duration = _realistic_duration(task.estimated_time_hours)
        
        # Handle optional tasks
        priority = task.priority
        if task.is_optional:
            priority = "low"
            
        tasks.append({
            "name": task.name,
            "original_duration": raw_duration,
            "duration": realistic_duration,
            "deadline": deadline_minutes,
            "priority": priority,
            "difficulty": task.difficulty,
            "is_optional": task.is_optional,
        })
    
    # Enforce Deep Work constraints: Max 2 hard tasks > 60 mins
    hard_tasks = [t for t in tasks if t["difficulty"] == "hard" and t["duration"] > 60]
    if len(hard_tasks) > MAX_DEEP_WORK_BLOCKS:
        # Move excess hard tasks to overflow/optional
        for i in range(MAX_DEEP_WORK_BLOCKS, len(hard_tasks)):
            task_name = hard_tasks[i]["name"]
            # Find in main list and mark optional/low priority
            for t in tasks:
                if t["name"] == task_name:
                    t["priority"] = "low"
                    t["is_optional"] = True
                    break
    
    # Apply mood adjustment to durations
    apply_mood_adjustment(tasks, request.preferences.mood)
    
    # Convert fixed slots
    fixed_slots = []
    for slot in request.fixed_slots:
        fixed_slots.append({
            "name": slot.name,
            "start": time_to_minutes(slot.start_time) - day_start,
            "end": time_to_minutes(slot.end_time) - day_start,
        })
    
    # S6 Fix: Validate fixed slots don't overlap before solving
    is_valid, error_msg = _validate_fixed_slots(request.fixed_slots)
    if not is_valid:
        return ScheduleResponse(status="infeasible", error=error_msg)
    
    # Build model
    model = cp_model.CpModel()
    
    # Fixed slot intervals
    fixed_intervals = []
    for slot in fixed_slots:
        slot_start = model.NewIntVar(slot["start"], slot["start"], f"slot_start_{slot['name']}")
        slot_end = model.NewIntVar(slot["end"], slot["end"], f"slot_end_{slot['name']}")
        slot_interval = model.NewIntervalVar(
            slot_start, slot["end"] - slot["start"], slot_end, f"slot_{slot['name']}"
        )
        fixed_intervals.append(slot_interval)
    
    # Task constraints with morning buffer
    starts, ends, task_intervals = add_task_constraints(
        model, tasks, effective_day_end, 
        morning_buffer=MORNING_BUFFER_MINUTES,
        add_no_overlap=False
    )
    
    # No overlap across all intervals
    model.AddNoOverlap(fixed_intervals + task_intervals)
    
    # Soft constraints
    penalties = build_soft_penalties(
        model, tasks, starts, request.preferences, day_start
    )
    
    # Apply learned constraints from user history
    if learned_constraints:
        learned_penalties = add_learned_constraints(
            model, tasks, starts, ends, learned_constraints, day_start
        )
        penalties.extend(learned_penalties)
    
    # Objective - multi-component optimization for balanced schedules
    build_objective(
        model, tasks, starts, ends, penalties, 
        day_end=effective_day_end, 
        morning_buffer=MORNING_BUFFER_MINUTES,
        work_style=request.preferences.work_style
    )
    
    # Solve with time limit and parallel search
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0  # 10 second limit
    solver.parameters.num_search_workers = 4      # Parallel search
    status = solver.Solve(model)
    
    # Build response with proper status handling
    if status == cp_model.OPTIMAL:
        blocks = _build_schedule_blocks(solver, tasks, starts, ends, fixed_slots, day_start)
        return ScheduleResponse(status="optimal", schedule=blocks)
    
    elif status == cp_model.FEASIBLE:
        # Solution found but may not be optimal (possibly hit time limit)
        blocks = _build_schedule_blocks(solver, tasks, starts, ends, fixed_slots, day_start)
        return ScheduleResponse(status="feasible", schedule=blocks)
    
    elif status == cp_model.INFEASIBLE:
        error = _build_error(status, tasks, fixed_slots, DAY_END)
        return ScheduleResponse(status="infeasible", error=error)
    
    elif status == cp_model.MODEL_INVALID:
        return ScheduleResponse(status="infeasible", error="Model constraints are invalid - please check your input")
    
    else:  # UNKNOWN - usually means timeout without solution
        return ScheduleResponse(status="infeasible", error="Solver timed out without finding a solution. Try reducing tasks or extending time window.")


def _build_schedule_blocks(solver, tasks, starts, ends, fixed_slots, day_start):
    """Build schedule blocks from solver solution."""
    blocks = []
    for i, task in enumerate(tasks):
        start_mins = solver.Value(starts[i])
        end_mins = solver.Value(ends[i])
        
        reason = _build_reason(task, start_mins, fixed_slots)
        
        blocks.append(ScheduledBlock(
            task_name=task["name"],
            start_time=minutes_to_time(start_mins, day_start),
            end_time=minutes_to_time(end_mins, day_start),
            reason=reason,
        ))
    
    blocks.sort(key=lambda b: b.start_time)
    
    # Inject visible breaks and morning routine
    blocks = _inject_morning_routine(blocks, day_start)
    blocks = _inject_breaks(blocks, day_start)
    
    return blocks


def _inject_morning_routine(blocks: list, day_start: int) -> list:
    """Add morning routine block at start of day.

    The routine block is capped at MAX_MORNING_ROUTINE_MINUTES; any surplus
    gap before the first task is shown as flexible "Open Time".
    """
    if not blocks:
        return blocks

    # Morning routine: from day start to first task
    first_task_start = time_to_minutes(blocks[0].start_time)
    gap = first_task_start - day_start

    if gap <= 0:
        return blocks

    routine_len = min(gap, MAX_MORNING_ROUTINE_MINUTES)
    prefix = [ScheduledBlock(
        task_name="🌅 Morning Routine",
        start_time=minutes_to_time(day_start),
        end_time=minutes_to_time(day_start + routine_len),
        reason="Time for coffee, breakfast, and getting ready"
    )]

    if gap > routine_len:
        prefix.append(ScheduledBlock(
            task_name="🗓️ Open Time",
            start_time=minutes_to_time(day_start + routine_len),
            end_time=minutes_to_time(first_task_start),
            reason="Flexible, unscheduled time before your first task"
        ))

    return prefix + blocks


def _inject_breaks(blocks: list, day_start: int, min_break_minutes: int = 15) -> list:
    """Add visible break blocks between tasks when there's a gap."""
    if len(blocks) < 2:
        return blocks
    
    result = []
    for i, block in enumerate(blocks):
        result.append(block)
        
        if i < len(blocks) - 1:
            next_block = blocks[i + 1]
            current_end = time_to_minutes(block.end_time)
            next_start = time_to_minutes(next_block.start_time)
            gap = next_start - current_end
            
            if gap >= min_break_minutes:
                # Check if this is lunch time (around 12:00-13:00)
                if 720 <= current_end <= 780 or 720 <= next_start <= 780:
                    break_name = "🍽️ Lunch Break"
                    break_reason = "Time to eat and recharge"
                elif gap >= 60:
                    break_name = "🎯 Focus Break"
                    break_reason = "Longer break - good for a walk or personal task"
                else:
                    break_name = "☕ Break"
                    break_reason = "Rest and reset before next task"

                # Cap the break; surplus becomes flexible "Open Time".
                break_len = min(gap, MAX_BREAK_MINUTES)
                result.append(ScheduledBlock(
                    task_name=break_name,
                    start_time=block.end_time,
                    end_time=minutes_to_time(current_end + break_len),
                    reason=break_reason
                ))

                if gap > break_len:
                    result.append(ScheduledBlock(
                        task_name="🗓️ Open Time",
                        start_time=minutes_to_time(current_end + break_len),
                        end_time=next_block.start_time,
                        reason="Flexible, unscheduled time"
                    ))
    
    return result


def _auto_insert_lunch(request: ScheduleRequest) -> None:
    """Add lunch slot if window spans noon and no conflict exists."""
    day_start = time_to_minutes(request.day_start_time)
    day_end = time_to_minutes(request.day_end_time)
    
    # Check if window spans lunch (12:00 = 720 minutes)
    if not (day_start < 720 < day_end):
        return
    
    # Check for existing lunch or conflict at noon
    for slot in request.fixed_slots:
        slot_start = time_to_minutes(slot.start_time)
        slot_end = time_to_minutes(slot.end_time)
        # Check if overlaps with 12:00-13:00
        if slot_start < 780 and slot_end > 720:
            return  # Conflict exists
        if "lunch" in slot.name.lower():
            return  # Already has lunch
    
    # Add lunch slot
    request.fixed_slots.append(
        FixedSlot(name="Lunch", start_time="12:00", end_time="13:00")
    )


def _build_reason(task: dict, start_mins: int, fixed_slots: list) -> str:
    """Build explanation for why task was scheduled at this time."""
    priority_reason = f"Scheduled as {task['priority']} priority task"
    
    if start_mins == 0:
        return f"{priority_reason}, scheduled at start of day"
    
    for slot in fixed_slots:
        if start_mins == slot["end"]:
            return f"{priority_reason}, scheduled after {slot['name']}"
    
    return priority_reason


def _build_error(status, tasks: list, fixed_slots: list, day_end: int) -> str:
    """Build error message for infeasible schedules."""
    if status == cp_model.MODEL_INVALID:
        return "Model constraints are invalid"
    
    total_task_time = sum(t["duration"] for t in tasks)
    slot_time = sum(s["end"] - s["start"] for s in fixed_slots)
    available_time = day_end - slot_time
    
    if total_task_time > available_time:
        return f"Total task duration ({total_task_time} min) exceeds available time ({available_time} min)"
    
    return "Tasks cannot be scheduled within deadlines and fixed time slots"


def _validate_fixed_slots(fixed_slots: list) -> tuple[bool, str]:
    """
    S6 Fix: Check for overlapping fixed slots before solving.
    
    Args:
        fixed_slots: List of FixedSlot objects
        
    Returns:
        (is_valid, error_message) tuple. error_message is None if valid.
    """
    for i, s1 in enumerate(fixed_slots):
        for s2 in fixed_slots[i + 1:]:
            s1_start = time_to_minutes(s1.start_time)
            s1_end = time_to_minutes(s1.end_time)
            s2_start = time_to_minutes(s2.start_time)
            s2_end = time_to_minutes(s2.end_time)
            
            # Check overlap: NOT (s1 ends before s2 starts OR s2 ends before s1 starts)
            if s1_end > s2_start and s2_end > s1_start:
                return False, f"Fixed slots overlap: '{s1.name}' ({s1.start_time}-{s1.end_time}) conflicts with '{s2.name}' ({s2.start_time}-{s2.end_time})"
    
    return True, None
