"""
Graphiti client initialization with OpenAI.
Loads configuration from environment variables.
"""

import os

from dotenv import load_dotenv
from graphiti_core import Graphiti
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

# Load .env file
load_dotenv()


def get_graphiti_client() -> Graphiti:
    """
    Initialize and return a Graphiti client using OpenAI.
    
    Required environment variables:
        NEO4J_URI: Neo4j connection URI
        NEO4J_USER: Neo4j username
        NEO4J_PASSWORD: Neo4j password
        OPENAI_API_KEY: OpenAI API key
    """
    neo4j_uri = os.getenv("NEO4J_URI")
    neo4j_user = os.getenv("NEO4J_USER")
    neo4j_password = os.getenv("NEO4J_PASSWORD")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    
    if not all([neo4j_uri, neo4j_user, neo4j_password]):
        raise ValueError("Missing required Neo4j environment variables")
    
    if not openai_api_key:
        raise ValueError("Missing OPENAI_API_KEY environment variable")
    
    # LLM configuration for OpenAI
    # temperature=0 maximizes determinism for extraction tasks
    llm_config = LLMConfig(
        api_key=openai_api_key,
        model="gpt-4o-mini",
        small_model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        temperature=0,  # Added for extraction determinism
    )
    
    return Graphiti(
        neo4j_uri,
        neo4j_user,
        neo4j_password,
        llm_client=OpenAIGenericClient(config=llm_config),
        embedder=OpenAIEmbedder(
            config=OpenAIEmbedderConfig(
                api_key=openai_api_key,
                embedding_model="text-embedding-3-small",
                base_url="https://api.openai.com/v1",
            )
        ),
        cross_encoder=OpenAIRerankerClient(
            config=LLMConfig(
                api_key=openai_api_key,
                model="gpt-4o-mini",
                base_url="https://api.openai.com/v1",
            )
        ),
    )


# Singleton instance
_client: Graphiti | None = None
_initialized: bool = False


def get_client() -> Graphiti:
    """Get or create the singleton Graphiti client.
    
    WARNING: This returns an uninitialized client!
    Call get_initialized_client() for full functionality.
    """
    global _client
    if _client is None:
        _client = get_graphiti_client()
    return _client


async def get_initialized_client() -> Graphiti:
    """Get an initialized Graphiti client with indices and constraints built.
    
    This MUST be called before any add_episode() or add_triplet() operations.
    Per official Graphiti docs, build_indices_and_constraints() is required.
    
    Returns:
        Graphiti: Fully initialized client ready for use.
    """
    global _client, _initialized
    
    if _client is None:
        _client = get_graphiti_client()
    
    if not _initialized:
        await _client.build_indices_and_constraints()
        _initialized = True
    
    return _client
