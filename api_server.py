"""FastAPI server for Pulse Scheduler with LangGraph extraction."""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime, timedelta
from threading import Lock
import os
import sys
from pathlib import Path

# LangGraph
from langgraph_flow import extraction_graph, ExtractionState
from langchain_core.messages import HumanMessage, AIMessage

# Graphiti
from graphiti_client.resilient_client import resilient_client, patterns_to_constraints
from graphiti_client.pattern_extractor import store_user_defaults, store_edit, extract_patterns

# Solver
solver_path = Path(__file__).parent / "or-tools-scheduler" / "or-tools-scheduler"
sys.path.insert(0, str(solver_path))
from scheduler.solver import generate_schedule
from scheduler.models import ScheduleRequest, TaskInput, FixedSlot, UserPreferences

app = FastAPI(title="Pulse Scheduler")

# Serve static files
frontend_path = Path(__file__).parent / "frontend"
frontend_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")

# Session storage with thread safety (BUG-016 fix)
extraction_sessions: dict = {}
session_lock = Lock()
SESSION_TTL_HOURS = 1  # Sessions expire after 1 hour (BUG-017 fix)


class ExtractRequest(BaseModel):
    text: str
    session_id: str = "default"
    user_id: str = "demo_user"


class ContinueRequest(BaseModel):
    text: str
    session_id: str
    user_id: str


class FeedbackRequest(BaseModel):
    user_id: str = "demo_user"
    task_name: str
    action: str = "move"
    from_time: Optional[str] = None
    to_time: Optional[str] = None


@app.get("/")
async def root():
    return FileResponse(str(frontend_path / "index.html"))


def _cleanup_expired_sessions():
    """Remove sessions older than SESSION_TTL_HOURS. Must be called within session_lock."""
    cutoff = datetime.now() - timedelta(hours=SESSION_TTL_HOURS)
    expired = [
        sid for sid, state in extraction_sessions.items()
        if state.get("_created_at", datetime.min) < cutoff
    ]
    for sid in expired:
        del extraction_sessions[sid]
    if expired:
        print(f"[CLEANUP] Removed {len(expired)} expired session(s)")


@app.post("/api/extract")
async def extract(req: ExtractRequest):
    """
    Extract scheduling data from user input using LangGraph.
    """
    import traceback
    
    try:
        session_id = req.session_id
        
        # Thread-safe session access (BUG-016 fix)
        with session_lock:
            # Cleanup expired sessions (BUG-017 fix)
            _cleanup_expired_sessions()
            
            # Initialize or get session state
            if session_id not in extraction_sessions:
                extraction_sessions[session_id] = {
                    "user_id": req.user_id,
                    "messages": [],
                    "user_context": {},
                    "extracted_data": None,
                    "validation_issues": [],
                    "attempt_count": 0,
                    "final_result": None,
                    "_created_at": datetime.now()  # Track creation time
                }
            
            state = extraction_sessions[session_id].copy()  # Copy to avoid mutation
        
        state["messages"].append(HumanMessage(content=req.text))
        
        print(f"[DEBUG] Running extraction for session {session_id}")
        print(f"[DEBUG] User input: {req.text[:100]}...")
        
        # Run extraction graph (outside lock for performance)
        result = await extraction_graph.ainvoke(state)
        print(f"[DEBUG] Extraction complete, result keys: {result.keys() if result else 'None'}")
        
        # Handle None result
        if not result:
            return {
                "status": "error",
                "error": "Extraction returned empty result. Please try again.",
                "tasks": [],
                "fixed_slots": []
            }
        
        # Thread-safe update session
        with session_lock:
            extraction_sessions[session_id] = result
        
        # Check if we need more input
        if result.get("validation_issues"):
            # Get the follow-up message
            ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
            follow_up = ai_messages[-1].content if ai_messages else "Could you provide more details?"
            
            return {
                "status": "incomplete",
                "follow_up": follow_up,
                "partial_data": result.get("extracted_data")
            }
        
        # Safety check: if final_result is None, something went wrong
        final = result.get("final_result")
        if not final:
            return {
                "status": "incomplete",
                "follow_up": "I need a bit more information. What tasks do you need to schedule, and how long will each take?",
                "partial_data": result.get("extracted_data")
            }
        
        # Store user defaults if we have new ones
        if final.get("wake_time") or final.get("sleep_time"):
            await store_user_defaults(
                req.user_id,
                final.get("wake_time", "09:00"),
                final.get("sleep_time", "22:00")
            )
        
        # Clean up session (thread-safe)
        with session_lock:
            if session_id in extraction_sessions:
                del extraction_sessions[session_id]
        
        # Transform tasks to frontend format
        tasks = []
        for t in final.get("tasks", []):
            tasks.append({
                "name": t.get("name"),
                "priority": t.get("priority", "medium"),
                "hours": t.get("estimated_time_hours", 1.0),  # Frontend expects "hours"
                "deadline": t.get("deadline"),
                "difficulty": t.get("difficulty", "medium"),
                "is_vague": t.get("is_vague", False)
            })
        
        # Transform fixed_slots to frontend format
        fixed_slots = []
        for s in final.get("fixed_slots", []):
            fixed_slots.append({
                "name": s.get("name"),
                "start": s.get("start_time"),  # Frontend expects "start"
                "end": s.get("end_time")       # Frontend expects "end"
            })
        
        return {
            "status": "complete",
            "tasks": tasks,
            "fixed_slots": fixed_slots,
            "preferences": final.get("preferences", {}),
            "wake_time": final.get("wake_time", "09:00"),
            "sleep_time": final.get("sleep_time", "22:00")
        }
    
    except Exception as e:
        print(f"[ERROR] Extraction failed: {traceback.format_exc()}")
        return {
            "status": "error",
            "error": str(e),
            "tasks": [],
            "fixed_slots": []
        }


@app.post("/api/extract/continue")
async def extract_continue(req: ContinueRequest):
    """Continue extraction with additional user input."""
    return await extract(ExtractRequest(
        text=req.text,
        session_id=req.session_id,
        user_id=req.user_id
    ))


@app.post("/api/schedule")
async def schedule(data: dict):
    """
    Generate schedule using OR-Tools with learned constraints.
    """
    user_id = data.get("user_id", "demo_user")
    
    # Fetch learned patterns from Graphiti
    user_context = await resilient_client.get_user_context(user_id)
    learned_constraints = patterns_to_constraints(user_context.get("patterns", {}))
    
    # Log for debugging
    if learned_constraints.get("avoid_time_slots") or learned_constraints.get("prefer_time_slots"):
        print(f"[schedule] Applying learned constraints: {learned_constraints}")
    
    # Build ScheduleRequest
    try:
        tasks = [
            TaskInput(
                name=t["name"],
                priority=t.get("priority", "medium"),
                estimated_time_hours=t.get("estimated_time_hours") or t.get("hours", 1.0),
                deadline=date.fromisoformat(t["deadline"]) if isinstance(t.get("deadline"), str) else t.get("deadline", date.today()),
                difficulty=t.get("difficulty", "medium")
            )
            for t in data.get("tasks", [])
        ]
        
        fixed_slots = [
            FixedSlot(
                name=s["name"],
                start_time=s.get("start_time") or s.get("start"),
                end_time=s.get("end_time") or s.get("end")
            )
            for s in data.get("fixed_slots", [])
        ]
        
        preferences = UserPreferences(
            energy_peak=data.get("preferences", {}).get("energy_peak", "morning"),
            mood=data.get("preferences", {}).get("mood", "normal")
        )
        
        request = ScheduleRequest(
            tasks=tasks,
            fixed_slots=fixed_slots,
            preferences=preferences,
            day_start_time=data.get("wake_time", "09:00"),
            day_end_time=data.get("sleep_time", "22:00"),
            date=date.today()
        )
    except Exception as e:
        return {
            "status": "error",
            "error": f"Invalid request data: {str(e)}",
            "schedule": [],
            "overflow_tasks": []
        }
    
    # Generate schedule with learned constraints
    try:
        response = generate_schedule(request, learned_constraints=learned_constraints)
    except Exception as e:
        return {
            "status": "error",
            "error": f"Scheduler error: {str(e)}",
            "schedule": [],
            "overflow_tasks": []
        }
    
    return {
        "status": response.status,
        "schedule": [
            {
                "task": block.task_name,
                "start": block.start_time,
                "end": block.end_time,
                "reason": block.reason
            }
            for block in response.schedule
        ],
        "overflow_tasks": response.overflow_tasks,
        "error": response.error
    }


@app.post("/api/feedback")
async def feedback(req: FeedbackRequest):
    """
    Store user feedback/edit for learning.
    """
    edit_data = {
        "task_name": req.task_name,
        "action": req.action,
        "from_time": req.from_time,
        "to_time": req.to_time
    }
    
    # Store via resilient client (handles Neo4j being down)
    stored = await resilient_client.store_edit(req.user_id, edit_data)
    
    return {
        "ok": True,
        "stored_to_neo4j": stored,
        "should_reschedule": True
    }


@app.get("/api/patterns/{user_id}")
async def patterns(user_id: str):
    """Get learned patterns for debugging."""
    return await extract_patterns(user_id)


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    neo4j_available = resilient_client.is_available()
    return {
        "status": "healthy",
        "neo4j_available": neo4j_available
    }


if __name__ == "__main__":
    import uvicorn
    print("Starting Pulse Scheduler at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
