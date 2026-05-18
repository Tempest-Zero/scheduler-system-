"""
System prompts for LLM extraction.

IMPORTANT: Prompts contain INSTRUCTIONS only, never schema definitions.
Schema enforcement is handled by LangChain's structured output.
"""

EXTRACTION_SYSTEM_PROMPT = """You are extracting scheduling information from user text.

DETECTION RULES:

1. PAST VS FUTURE:
   - Past tense complaints → is_past_description = true
   - Future intentions → extract as tasks
   - Examples of past: "today was terrible", "had back-to-back meetings"
   - Examples of future: "tomorrow I need to", "I have to finish"

2. TIME WINDOW:
   - Extract wake time: "wake at 7" → "07:00"
   - Extract sleep time: "done by 9pm" → "21:00"
   - Infer from patterns: "early bird" → wake "06:00", "night owl" → sleep "01:00"

3. TASKS:
   - Only extract actionable future items
   - Complaints are NOT tasks
   - Infer priority from tone: frustrated/urgent = high, casual = low
   - Infer difficulty: complex = hard, routine = easy

4. DURATIONS:
   - "quick" → 0.5 hours
   - "about an hour" → 1 hour
   - "long" or "deep work" → 2+ hours
   - If unclear, leave empty (will be asked)

5. FIXED COMMITMENTS:
   - Meetings, classes with specific times
   - "standup at 10" → fixed slot 10:00-10:30
   - "meeting 2-3pm" → fixed slot 14:00-15:00

6. PREFERENCES & CONTEXT:
   - Energy: "tired/exhausted" → mood="low", "pumped" → mood="high"
   - Peak: "morning person" → energy_peak="morning"
   - Style: "deep work/focus" → work_style="focused", "batches" → work_style="focused"
   - Style: "chill/spread out" → work_style="spread_out"
   - Optional: "if I have time", "maybe do X" → is_optional=True

7. VAGUE DETECTION:
   - Generic names like "stuff", "things", "work" → is_vague = true
   - Missing duration + unclear context → is_vague = true"""


def build_context_prompt(user_context: dict) -> str:
    """
    Build context string from user history.
    
    This produces natural language, NOT schema definitions.
    
    Args:
        user_context: {defaults: {...}, patterns: {...}}
    
    Returns:
        Human-readable context string
    """
    parts = []
    
    defaults = user_context.get("defaults", {})
    if defaults.get("wake_time"):
        parts.append(f"User typically wakes at {defaults['wake_time']}.")
    if defaults.get("sleep_time"):
        parts.append(f"User typically winds down at {defaults['sleep_time']}.")
    
    patterns = user_context.get("patterns", {})
    avoided = patterns.get("avoided_times", {})
    preferred = patterns.get("time_preferences", {})
    
    for task, hours in avoided.items():
        hours_str = ", ".join(f"{h}:00" for h in hours)
        parts.append(f"User prefers NOT to schedule '{task}' around {hours_str}.")
    
    for task, hours in preferred.items():
        hours_str = ", ".join(f"{h}:00" for h in hours)
        parts.append(f"User prefers '{task}' around {hours_str}.")
    
    if parts:
        return "USER CONTEXT:\n" + "\n".join(parts)
    return ""
