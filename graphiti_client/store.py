"""
Episode storage functions for Graphiti.
Uses EpisodeType.json for direct storage of pre-structured data.

ARCHITECTURE: Task 1 does NLP extraction → Task 3 stores structured JSON.
This bypasses Graphiti's LLM extraction, avoiding the Map error.
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional

from graphiti_core.nodes import EpisodeType

from .client import get_initialized_client


async def store_cold_start(user_id: str, user_data: Dict[str, Any]) -> None:
    """
    Store user's initial preferences at cold start.
    
    Args:
        user_id: Unique user identifier (used as group_id for namespacing)
        user_data: Structured JSON data from Task 1 containing:
            - preferred_wake_time: int (0-23)
            - preferred_sleep_time: int (0-23)
            - productivity_style: str ("morning_person", "night_owl", "flexible")
            - tasks: list of task objects
            - etc.
    """
    client = await get_initialized_client()
    
    # Convert to JSON string for EpisodeType.json
    episode_body = json.dumps({
        "type": "cold_start",
        "user_id": user_id,
        "timestamp": datetime.now().isoformat(),
        "data": user_data
    })
    
    await client.add_episode(
        name=f"cold_start_{user_id}",
        episode_body=episode_body,
        source=EpisodeType.json,  # Direct storage, no LLM extraction
        source_description="User onboarding - initial preferences",
        reference_time=datetime.now(),
        group_id=user_id,
    )


async def store_acceptance(user_id: str, schedule_data: Dict[str, Any]) -> None:
    """
    Store confirmation when user accepts a schedule.
    
    Args:
        user_id: Unique user identifier
        schedule_data: Structured JSON data containing:
            - schedule_id: str
            - accepted_blocks: list of time blocks
            - etc.
    """
    client = await get_initialized_client()
    
    episode_body = json.dumps({
        "type": "acceptance",
        "user_id": user_id,
        "timestamp": datetime.now().isoformat(),
        "feedback_type": "accepted",
        "data": schedule_data
    })
    
    await client.add_episode(
        name=f"acceptance_{user_id}_{datetime.now().isoformat()}",
        episode_body=episode_body,
        source=EpisodeType.json,  # Direct storage, no LLM extraction
        source_description="Schedule feedback - accepted",
        reference_time=datetime.now(),
        group_id=user_id,
    )


async def store_edit(
    user_id: str,
    edit_data: Dict[str, Any],
) -> None:
    """
    Store learning when user edits a scheduled block.
    
    Args:
        user_id: Unique user identifier
        edit_data: Structured JSON data containing:
            - task_name: str
            - original_start_hour: int
            - new_start_hour: int
            - reason: Optional[str]
    """
    client = await get_initialized_client()
    
    episode_body = json.dumps({
        "type": "edit",
        "user_id": user_id,
        "timestamp": datetime.now().isoformat(),
        "feedback_type": "edited",
        "data": edit_data
    })
    
    await client.add_episode(
        name=f"edit_{user_id}_{datetime.now().isoformat()}",
        episode_body=episode_body,
        source=EpisodeType.json,  # Direct storage, no LLM extraction
        source_description="Schedule feedback - edited",
        reference_time=datetime.now(),
        group_id=user_id,
    )
