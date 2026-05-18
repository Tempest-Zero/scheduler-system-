"""Hard constraints for schedule optimization."""

# Morning buffer constant - imported from solver
MORNING_BUFFER_MINUTES = 30


def add_task_constraints(model, tasks, day_end, morning_buffer=MORNING_BUFFER_MINUTES, add_no_overlap=True):
    """
    Add hard constraints for tasks.
    
    Args:
        model: OR-Tools CpModel
        tasks: List of task dicts
        day_end: End of scheduling window (relative minutes)
        morning_buffer: Minutes after wake time before first task
        add_no_overlap: Whether to add no-overlap constraint
        
    Returns:
        (starts, ends, intervals) - Variable lists for solver
    """
    starts, ends, intervals = [], [], []

    for i, task in enumerate(tasks):
        # Task can start after morning buffer, must end before day_end
        start = model.NewIntVar(morning_buffer, day_end, f"start_{i}")
        end = model.NewIntVar(morning_buffer, day_end, f"end_{i}")
        interval = model.NewIntervalVar(start, task["duration"], end, f"interval_{i}")

        # Hard constraint: task must end before deadline
        model.Add(end <= task["deadline"])

        starts.append(start)
        ends.append(end)
        intervals.append(interval)

    if add_no_overlap:
        model.AddNoOverlap(intervals)
    
    return starts, ends, intervals
