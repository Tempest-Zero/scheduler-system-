"""
LLM extraction using LangChain structured output.

This module uses LangChain's with_structured_output() which converts
Pydantic schemas to OpenAI function calling specs. The schema is sent
in the API 'tools' parameter, NOT in conversation text.
"""

import os
from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from .schemas import ExtractionResultSchema
from .prompts import EXTRACTION_SYSTEM_PROMPT, build_context_prompt


def get_extraction_llm():
    """
    Create LLM with structured output.
    
    The schema is converted to OpenAI function calling spec internally.
    """
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=os.getenv("OPENAI_API_KEY")
    )
    
    # This converts Pydantic schema to function calling spec
    # Schema goes in API 'tools' parameter, not conversation
    return llm.with_structured_output(ExtractionResultSchema)


def extract_with_context(
    user_input: str,
    history: Optional[list] = None,
    user_context: Optional[dict] = None
) -> dict:
    """
    Extract structured data from user input.
    
    Args:
        user_input: User's natural language input
        history: Previous conversation messages
        user_context: Learned user context from Graphiti
    
    Returns:
        Extracted data as dict (from Pydantic model)
    """
    llm = get_extraction_llm()
    
    # Build system prompt with context (NO schema in text)
    system_content = EXTRACTION_SYSTEM_PROMPT
    if user_context:
        context_str = build_context_prompt(user_context)
        if context_str:
            system_content = f"{context_str}\n\n{system_content}"
    
    # Build messages
    messages = [SystemMessage(content=system_content)]
    
    if history:
        messages.extend(history)
    
    messages.append(HumanMessage(content=user_input))
    
    try:
        # Invoke with structured output
        result: ExtractionResultSchema = llm.invoke(messages)
        
        # Handle None response from LLM
        if result is None:
            return {
                "tasks": [],
                "fixed_slots": [],
                "is_past_description": False,
                "_error": "LLM returned empty response. Please try again."
            }
        
        return result.model_dump()
    except Exception as e:
        return {
            "tasks": [],
            "fixed_slots": [],
            "is_past_description": False,
            "_error": str(e)
        }
