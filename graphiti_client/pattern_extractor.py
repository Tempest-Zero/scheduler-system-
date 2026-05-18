"""
Pattern extraction and constraint conversion for learned preferences.

This module provides:
- User context retrieval (defaults + patterns)
- Pattern to constraint conversion with frequency weighting
- Dual storage (episode + future triplet support)
"""

import json
from datetime import datetime
from typing import Optional
from .fetch import fetch_preferences
from .store import store_cold_start


async def get_user_context(user_id: str) -> dict:
    """
    Fetch complete user context from Graphiti.
    
    Args:
        user_id: User identifier
    
    Returns:
        {
            "defaults": {"wake_time": str|None, "sleep_time": str|None},
            "patterns": {"avoided_times": {task: [hours]}, "time_preferences": {task: [hours]}}
        }
    """
    context = {
        "defaults": {"wake_time": None, "sleep_time": None},
        "patterns": {"avoided_times": {}, "time_preferences": {}}
    }
    
    try:
        results = await fetch_preferences(
            user_id,
            "wake sleep time preferences schedule edit feedback user defaults"
        )
        
        for result in results:
            # Get content from result
            content = str(result.fact) if hasattr(result, 'fact') else str(result)
            
            try:
                data = json.loads(content)
                _process_episode(data, context)
            except (json.JSONDecodeError, TypeError):
                continue
                
    except Exception as e:
        print(f"[pattern_extractor] Error fetching context: {e}")
    
    return context


def _process_episode(data: dict, context: dict) -> None:
    """Process a single episode and update context."""
    episode_type = data.get("type")
    
    # User defaults
    if episode_type == "user_defaults":
        if data.get("wake_time"):
            context["defaults"]["wake_time"] = data["wake_time"]
        if data.get("sleep_time"):
            context["defaults"]["sleep_time"] = data["sleep_time"]
    
    # Edit patterns
    elif episode_type == "edit" or data.get("feedback_type") == "edited":
        edit_data = data.get("data", data)
        task_name = edit_data.get("task_name", "").lower()
        
        if not task_name:
            return
        
        # Extract hours - handle multiple field names
        from_hour = _extract_hour(edit_data.get("original_start_hour") or edit_data.get("from_hour") or edit_data.get("from_time"))
        to_hour = _extract_hour(edit_data.get("new_start_hour") or edit_data.get("to_hour") or edit_data.get("to_time"))
        
        # Record avoidance
        if from_hour is not None:
            if task_name not in context["patterns"]["avoided_times"]:
                context["patterns"]["avoided_times"][task_name] = []
            context["patterns"]["avoided_times"][task_name].append(from_hour)
        
        # Record preference
        if to_hour is not None:
            if task_name not in context["patterns"]["time_preferences"]:
                context["patterns"]["time_preferences"][task_name] = []
            context["patterns"]["time_preferences"][task_name].append(to_hour)


def _extract_hour(value) -> Optional[int]:
    """Extract hour from various formats."""
    if value is None:
        return None
    
    if isinstance(value, int):
        return value
    
    if isinstance(value, float):
        return int(value)
    
    if isinstance(value, str):
        # Handle "HH:MM" format
        if ":" in value:
            try:
                return int(value.split(":")[0])
            except (ValueError, IndexError):
                return None
        # Handle plain number string
        try:
            return int(value)
        except ValueError:
            return None
    
    return None


def patterns_to_constraints(patterns: dict) -> dict:
    """
    Convert learned patterns to solver constraint format.
    
    Implements frequency weighting: more edits = stronger constraint.
    
    Args:
        patterns: {"avoided_times": {task: [hours]}, "time_preferences": {task: [hours]}}
    
    Returns:
        {
            "avoid_time_slots": [(task, start_hour, end_hour, penalty_weight)],
            "prefer_time_slots": [(task, start_hour, end_hour, bonus_weight)]
        }
    """
    constraints = {
        "avoid_time_slots": [],
        "prefer_time_slots": []
    }
    
    BASE_AVOID_WEIGHT = 200
    BASE_PREFER_WEIGHT = -100
    MAX_AVOID_WEIGHT = 1000
    MAX_PREFER_WEIGHT = -500
    
    # Process avoidance patterns with frequency weighting
    for task, hours in patterns.get("avoided_times", {}).items():
        # Count occurrences of each hour
        hour_counts = {}
        for h in hours:
            hour_counts[h] = hour_counts.get(h, 0) + 1
        
        for hour, count in hour_counts.items():
            weight = min(BASE_AVOID_WEIGHT * count, MAX_AVOID_WEIGHT)
            constraints["avoid_time_slots"].append((task, hour, hour + 1, weight))
    
    # Process preference patterns with frequency weighting
    for task, hours in patterns.get("time_preferences", {}).items():
        hour_counts = {}
        for h in hours:
            hour_counts[h] = hour_counts.get(h, 0) + 1
        
        for hour, count in hour_counts.items():
            weight = max(BASE_PREFER_WEIGHT * count, MAX_PREFER_WEIGHT)
            constraints["prefer_time_slots"].append((task, hour, hour + 1, weight))
    
    return constraints


async def store_user_defaults(user_id: str, wake_time: str, sleep_time: str) -> None:
    """Store user's default wake/sleep times."""
    await store_cold_start(user_id, {
        "type": "user_defaults",
        "wake_time": wake_time,
        "sleep_time": sleep_time,
        "timestamp": datetime.now().isoformat()
    })


async def store_edit(user_id: str, edit_data: dict) -> None:
    """
    Store user edit for learning.
    
    Args:
        edit_data: {
            "task_name": str,
            "from_time": str (HH:MM),
            "to_time": str (HH:MM),
            "action": str (optional)
        }
    """
    await store_cold_start(user_id, {
        "type": "edit",
        "feedback_type": "edited",
        "data": edit_data,
        "timestamp": datetime.now().isoformat()
    })


# Alias for backward compatibility
async def get_user_defaults(user_id: str) -> dict:
    """Get user defaults only. Use get_user_context for full context."""
    context = await get_user_context(user_id)
    return context["defaults"]


async def extract_patterns(user_id: str) -> dict:
    """Get patterns only. Use get_user_context for full context."""
    context = await get_user_context(user_id)
    return context["patterns"]
