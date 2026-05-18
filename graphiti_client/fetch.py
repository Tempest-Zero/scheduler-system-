"""
Preference retrieval functions for Graphiti.
Uses search() to query the knowledge graph.
"""

from .client import get_initialized_client


async def fetch_preferences(user_id: str, query: str = "user preferences and patterns") -> list:
    """
    Fetch user preferences from the knowledge graph.
    
    Args:
        user_id: Unique user identifier (used as group_id for filtering)
        query: Search query string
        
    Returns:
        List of search results (edges with source/target nodes)
    """
    client = await get_initialized_client()
    
    # Use Graphiti's search API
    results = await client.search(
        query=query,
        group_ids=[user_id],
    )
    
    return results
