"""
Resilient Graphiti client with fallback and queue.
Handles Neo4j unavailability gracefully for demo resilience.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from .client import get_initialized_client

# Configuration
CACHE_TTL_SECONDS = 300  # 5 minutes
RECONNECT_INTERVAL_SECONDS = 60  # Wait before retrying connection

# In-memory fallback storage
_fallback_cache: Dict[str, Any] = {}
_cache_expiry: Dict[str, datetime] = {}


class ResilientGraphitiClient:
    """Wrapper that handles Neo4j failures gracefully."""
    
    def __init__(self):
        self._client = None
        self._neo4j_available = True
        self._last_check: Optional[datetime] = None
    
    async def get_client(self):
        """Get client, checking availability periodically."""
        now = datetime.now()
        
        # Don't spam connection attempts
        if self._last_check:
            seconds_since_check = (now - self._last_check).total_seconds()
            if seconds_since_check < RECONNECT_INTERVAL_SECONDS and not self._neo4j_available:
                return None
        
        try:
            self._client = await get_initialized_client()
            # Test connection with minimal query
            await self._client.search(query="health", group_ids=["_health_check"])
            self._neo4j_available = True
        except Exception as e:
            print(f"  [Resilient] Neo4j unavailable: {e}")
            self._neo4j_available = False
            self._client = None
        
        self._last_check = now
        return self._client if self._neo4j_available else None
    
    def is_available(self) -> bool:
        """Check if Neo4j is currently available."""
        return self._neo4j_available
    
    async def get_user_context(self, user_id: str) -> dict:
        """Get context with fallback to cache."""
        cache_key = f"context:{user_id}"
        
        # Try Neo4j first
        client = await self.get_client()
        if client:
            try:
                context = await self._fetch_context_from_neo4j(client, user_id)
                # Update cache on success
                _fallback_cache[cache_key] = context
                _cache_expiry[cache_key] = datetime.now() + timedelta(seconds=CACHE_TTL_SECONDS)
                return context
            except Exception as e:
                print(f"  [Resilient] Neo4j query failed: {e}")
        
        # Fall back to cache
        if cache_key in _fallback_cache:
            if datetime.now() < _cache_expiry.get(cache_key, datetime.min):
                print("  [Resilient] Using cached context (Neo4j unavailable)")
                return _fallback_cache[cache_key]
        
        # No cache, return defaults
        print("  [Resilient] No cache available, using defaults")
        return self._get_default_context()
    
    async def _fetch_context_from_neo4j(self, client, user_id: str) -> dict:
        """Fetch user context from Neo4j."""
        from .pattern_extractor import extract_patterns, get_user_defaults
        
        defaults = await get_user_defaults(user_id)
        patterns = await extract_patterns(user_id)
        
        return {
            "defaults": defaults,
            "patterns": patterns,
            "fetched_at": datetime.now().isoformat()
        }
    
    def _get_default_context(self) -> dict:
        """Return sensible defaults when no data available."""
        return {
            "defaults": {"wake_time": "09:00", "sleep_time": "22:00"},
            "patterns": {"avoided_times": {}, "time_preferences": {}},
            "fetched_at": None,
            "is_fallback": True
        }
    
    async def store_edit(self, user_id: str, edit_data: dict) -> bool:
        """Store edit with fallback to local queue."""
        client = await self.get_client()
        
        if client:
            try:
                await self._store_to_neo4j(client, user_id, edit_data)
                # Also flush any queued edits
                await self._flush_queue(client, user_id)
                return True
            except Exception as e:
                print(f"  [Resilient] Neo4j store failed: {e}")
        
        # Queue for later
        self._queue_edit(user_id, edit_data)
        return False
    
    async def _store_to_neo4j(self, client, user_id: str, edit_data: dict):
        """Store edit as episode (and optionally triplet)."""
        from .store import store_edit as episode_store
        
        # 1. Episode storage (backward compatible)
        await episode_store(user_id, edit_data)
        
        # 2. Triplet storage (new approach) - best effort
        try:
            await self._store_triplets(client, user_id, edit_data)
        except Exception as e:
            print(f"  [Resilient] Triplet storage failed (non-fatal): {e}")
    
    async def _store_triplets(self, client, user_id: str, edit_data: dict):
        """Store edit as triplets for structured graph."""
        from graphiti_core.nodes import EntityNode, EntityEdge
        
        task_name = edit_data.get("task_name")
        from_time = edit_data.get("from_time")
        to_time = edit_data.get("to_time")
        
        # Parse hours from time strings
        from_hour = None
        to_hour = None
        
        if from_time and isinstance(from_time, str) and ":" in from_time:
            from_hour = int(from_time.split(":")[0])
        if to_time and isinstance(to_time, str) and ":" in to_time:
            to_hour = int(to_time.split(":")[0])
        
        # Create triplets
        if task_name and from_hour is not None:
            # User avoids this time for this task
            source = EntityNode(
                name=user_id,
                labels=["User"],
                properties={}
            )
            target = EntityNode(
                name=task_name.lower(),
                labels=["Task"],
                properties={}
            )
            edge = EntityEdge(
                name="AVOIDS_TIME_FOR",
                fact=f"User avoids scheduling {task_name} at hour {from_hour}",
                source=source,
                target=target,
                properties={
                    "hour": from_hour,
                    "recorded_at": datetime.now().isoformat(),
                    "_schema_version": "1.0"
                }
            )
            await client.add_triplet(source, edge, target, group_id=user_id)
        
        if task_name and to_hour is not None:
            # User prefers this time for this task
            source = EntityNode(
                name=user_id,
                labels=["User"],
                properties={}
            )
            target = EntityNode(
                name=task_name.lower(),
                labels=["Task"],
                properties={}
            )
            edge = EntityEdge(
                name="PREFERS_TIME_FOR",
                fact=f"User prefers scheduling {task_name} at hour {to_hour}",
                source=source,
                target=target,
                properties={
                    "hour": to_hour,
                    "recorded_at": datetime.now().isoformat(),
                    "_schema_version": "1.0"
                }
            )
            await client.add_triplet(source, edge, target, group_id=user_id)
    
    def _queue_edit(self, user_id: str, edit_data: dict):
        """Queue edit for when Neo4j is back."""
        queue_key = f"queue:{user_id}"
        if queue_key not in _fallback_cache:
            _fallback_cache[queue_key] = []
        
        _fallback_cache[queue_key].append({
            "data": edit_data,
            "timestamp": datetime.now().isoformat()
        })
        
        queue_size = len(_fallback_cache[queue_key])
        print(f"  [Resilient] Edit queued (Neo4j unavailable). Queue size: {queue_size}")
    
    async def _flush_queue(self, client, user_id: str):
        """Flush queued edits when Neo4j is back."""
        queue_key = f"queue:{user_id}"
        
        if queue_key not in _fallback_cache or not _fallback_cache[queue_key]:
            return
        
        queue = _fallback_cache[queue_key]
        print(f"  [Resilient] Flushing {len(queue)} queued edits")
        
        for item in queue:
            try:
                await self._store_to_neo4j(client, user_id, item["data"])
            except Exception as e:
                print(f"  [Resilient] Failed to flush queued edit: {e}")
        
        _fallback_cache[queue_key] = []
    
    async def store_user_defaults(self, user_id: str, wake_time: str, sleep_time: str) -> bool:
        """Store user defaults (wake/sleep time)."""
        from .store import store_cold_start
        
        if await self.get_client():
            try:
                await store_cold_start(user_id, {
                    "type": "user_defaults",
                    "wake_time": wake_time,
                    "sleep_time": sleep_time,
                    "timestamp": datetime.now().isoformat()
                })
                return True
            except Exception as e:
                print(f"  [Resilient] Store defaults failed: {e}")
        return False
    
    def get_queue_size(self, user_id: str) -> int:
        """Get number of queued edits for debugging."""
        queue_key = f"queue:{user_id}"
        return len(_fallback_cache.get(queue_key, []))


# Singleton instance
resilient_client = ResilientGraphitiClient()


def patterns_to_constraints(patterns: dict) -> dict:
    """
    Convert patterns to solver constraint format.
    
    Args:
        patterns: {avoided_times: {task: [hours]}, time_preferences: {task: [hours]}}
    
    Returns:
        {avoid_time_slots: [(task, start_h, end_h, weight)], prefer_time_slots: [...]}
    """
    constraints = {
        "avoid_time_slots": [],
        "prefer_time_slots": []
    }
    
    BASE_AVOID_WEIGHT = 200
    BASE_PREFER_WEIGHT = -100
    
    for task, hours in patterns.get("avoided_times", {}).items():
        count = len(hours)
        # More occurrences = stronger signal (caps at 1000)
        weight = min(BASE_AVOID_WEIGHT * count, 1000)
        for hour in set(hours):  # Deduplicate
            constraints["avoid_time_slots"].append((task, hour, hour + 1, weight))
    
    for task, hours in patterns.get("time_preferences", {}).items():
        count = len(hours)
        # More occurrences = stronger bonus (caps at -500)
        weight = max(BASE_PREFER_WEIGHT * count, -500)
        for hour in set(hours):
            constraints["prefer_time_slots"].append((task, hour, hour + 1, weight))
    
    return constraints

