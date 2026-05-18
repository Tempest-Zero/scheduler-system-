"""Tests for extraction session lifecycle in the API server."""
from datetime import datetime, timedelta

import api_server


def test_cleanup_removes_only_expired_sessions():
    # Creation time is tracked in a separate dict because LangGraph drops
    # state keys it does not own; cleanup must read from that dict.
    api_server.extraction_sessions.clear()
    api_server.session_created_at.clear()

    now = datetime.now()
    api_server.extraction_sessions["fresh"] = {"messages": []}
    api_server.session_created_at["fresh"] = now
    api_server.extraction_sessions["stale"] = {"messages": []}
    api_server.session_created_at["stale"] = now - timedelta(hours=2)

    api_server._cleanup_expired_sessions()

    assert "fresh" in api_server.extraction_sessions
    assert "stale" not in api_server.extraction_sessions
    assert "stale" not in api_server.session_created_at


def test_cleanup_keeps_session_whose_state_lost_created_at():
    # Regression: after the extraction graph runs, the stored session dict no
    # longer carries a creation timestamp. The session must still survive
    # cleanup so multi-turn follow-ups keep their conversation history.
    api_server.extraction_sessions.clear()
    api_server.session_created_at.clear()

    api_server.extraction_sessions["s1"] = {"messages": ["turn-1"]}  # no _created_at
    api_server.session_created_at["s1"] = datetime.now()

    api_server._cleanup_expired_sessions()

    assert "s1" in api_server.extraction_sessions
