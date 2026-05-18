from ortools.sat.python import cp_model
from datetime import datetime
import json
from scheduler.model import create_model
from scheduler.constraint import add_task_constraints
from scheduler.objective import build_objective
from scheduler.utils import time_to_minutes
from data.sample_input import sample_input

# Parse input data
day_start = time_to_minutes(sample_input["day_start_time"])
day_end = time_to_minutes(sample_input["day_end_time"])
DAY_END = day_end - day_start
current_date = datetime.strptime(sample_input["date"], "%Y-%m-%d")

# Convert tasks to scheduler format
tasks = []
for task in sample_input["tasks"]:
    deadline_date = datetime.strptime(task["deadline"], "%Y-%m-%d")
    days_until_deadline = (deadline_date - current_date).days
    deadline_minutes = days_until_deadline * 24 * 60 + DAY_END
    
    tasks.append({
        "name": task["name"],
        "duration": int(task["estimated_time_hours"] * 60),
        "deadline": min(deadline_minutes, DAY_END),  # Cap at day end
        "priority": task["priority"]
    })

# Convert fixed slots
fixed_slots = []
for slot in sample_input["fixed_slots"]:
    fixed_slots.append({
        "name": slot["name"],
        "start": time_to_minutes(slot["start_time"]) - day_start,
        "end": time_to_minutes(slot["end_time"]) - day_start
    })

model = create_model()

# Add fixed slot intervals first
fixed_intervals = []
for slot in fixed_slots:
    slot_start = model.NewIntVar(slot["start"], slot["start"], f"slot_start_{slot['name']}")
    slot_end = model.NewIntVar(slot["end"], slot["end"], f"slot_end_{slot['name']}")
    slot_interval = model.NewIntervalVar(slot_start, slot["end"] - slot["start"], slot_end, f"slot_{slot['name']}")
    fixed_intervals.append(slot_interval)

# Add task constraints (skip no-overlap, we'll add it with fixed slots)
starts, ends, task_intervals = add_task_constraints(model, tasks, DAY_END, add_no_overlap=False)

# Combine all intervals and add no-overlap constraint
all_intervals = fixed_intervals + task_intervals
model.AddNoOverlap(all_intervals)

penalties = []  # add soft constraint penalties here

build_objective(model, tasks, starts, penalties)

solver = cp_model.CpSolver()
status = solver.Solve(model)

def minutes_to_time(minutes):
    """Convert minutes from day start to HH:MM format"""
    total_minutes = minutes + day_start
    hour = total_minutes // 60
    minute = total_minutes % 60
    return f"{hour:02d}:{minute:02d}"

if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
    schedule = []
    for i, task in enumerate(tasks):
        start_minutes = solver.Value(starts[i])
        end_minutes = solver.Value(ends[i])
        
        # Generate reason based on priority and scheduling
        priority_reason = f"Scheduled as {task['priority']} priority task"
        if start_minutes == 0:
            reason = f"{priority_reason}, scheduled at start of day"
        else:
            # Check if scheduled right after a fixed slot
            scheduled_after_slot = False
            for slot in fixed_slots:
                if start_minutes == slot["end"]:
                    reason = f"{priority_reason}, scheduled after {slot['name']}"
                    scheduled_after_slot = True
                    break
            if not scheduled_after_slot:
                reason = priority_reason
        
        schedule.append({
            "task_name": task["name"],
            "start_time": minutes_to_time(start_minutes),
            "end_time": minutes_to_time(end_minutes),
            "reason": reason
        })
    
    output = {"schedule": schedule}
    print(json.dumps(output, indent=2))
else:
    # Determine why scheduling failed
    reason = "Scheduling impossible"
    if status == cp_model.MODEL_INVALID:
        reason = "Model constraints are invalid"
    elif status == cp_model.INFEASIBLE:
        # Check for common issues
        total_task_time = sum(task["duration"] for task in tasks)
        available_time = DAY_END - sum(slot["end"] - slot["start"] for slot in fixed_slots)
        if total_task_time > available_time:
            reason = f"Total task duration ({total_task_time} min) exceeds available time ({available_time} min)"
        else:
            reason = "Tasks cannot be scheduled within deadlines and fixed time slots"
    
    output = {"error": reason}
    print(json.dumps(output, indent=2))
