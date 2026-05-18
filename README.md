# Pulse Scheduler

**An AI daily planner that turns a plain-English brain-dump into an optimized, time-blocked schedule — and learns from every edit you make.**

You type *"Tomorrow I wake up at 7, need to finish my report (~2hrs), hit the gym (1hr), and have a meeting at 2pm."* Pulse extracts the tasks, solves a constraint-satisfaction problem to lay them out around your fixed commitments and energy levels, and remembers how you reschedule things so future plans fit you better.

---

## Why it's interesting

Pulse is built from three independent subsystems that each solve a hard problem, wired together behind one API:

| Subsystem | Problem it solves | Technology |
|-----------|-------------------|------------|
| **Task 1 — NLP Extraction** | Turn messy natural language into clean, typed task data | LangGraph state machine + OpenAI structured output |
| **Task 2 — Schedule Optimizer** | Place tasks optimally around constraints (deadlines, meetings, energy, breaks) | Google OR-Tools CP-SAT constraint solver |
| **Task 3 — Learning Memory** | Remember user preferences and learn from schedule edits | Graphiti knowledge graph on Neo4j |

The interesting engineering is in how they connect — and in one bug worth reading about.

### The schema-leakage bug (and the fix)

Graphiti normally runs its own LLM to extract entities from text before storing them in Neo4j. That extraction produced nested `Map` types, which Neo4j **cannot** store as node properties — every write crashed with `CypherTypeError`.

The fix was an architectural one: **do all extraction in Task 1**, emit flat JSON with primitive values only, and have Task 3 store it via `EpisodeType.json`, which bypasses Graphiti's internal LLM entirely. Extraction intelligence lives in exactly one place, and storage became a dumb, reliable write.

```
Before:  User text -> Graphiti's LLM -> nested Maps -> Neo4j  CypherTypeError
After:   User text -> Task 1 LLM -> flat JSON -> EpisodeType.json -> Neo4j  OK
```

See [docs/architecture.md](docs/architecture.md) for the full write-up.

---

## Features

- **Natural-language input** — no forms; describe your day however you want.
- **Multi-turn clarification** — if a task is missing a duration or is too vague, the assistant asks a focused follow-up instead of guessing.
- **Human-centered scheduling** — morning routine buffer, mandatory breaks, lunch auto-insertion, a "tasks take 20% longer than you think" realism factor, and a deep-work cap.
- **Overflow handling** — when the day is too full, low-priority/late-deadline tasks are explicitly pushed to tomorrow rather than silently dropped.
- **Learns from edits** — move a task and Pulse records it; repeated edits become weighted constraints that bias future schedules.
- **Resilient by design** — if Neo4j is unavailable, the app falls back to an in-memory cache and queues writes for later instead of crashing.

---

## Architecture

```
                  +-------------------+
   "plan my day"  |   Task 1: NLP     |   LangGraph graph:
  --------------> |   Extraction      |   load context -> extract ->
                  |  (LangGraph+LLM)  |   validate -> reprompt/finalize
                  +---------+---------+
                            | structured JSON (flat primitives)
                            v
                  +-------------------+         +------------------+
                  |  Task 2: Solver   | <-----  |  Task 3: Memory  |
                  |  (OR-Tools CP-SAT)|  learned |  (Graphiti/Neo4j)|
                  +---------+---------+  constraints  +------+------+
                            | schedule              ^
                            v                       | edits / feedback
                  +-------------------+              |
                  |  Web UI (FastAPI) | -------------+
                  +-------------------+
```

The **learning loop**: a schedule edit -> stored in the knowledge graph -> on the next run, `patterns_to_constraints()` converts repeated patterns into weighted "avoid/prefer this hour" penalties fed straight into the OR-Tools objective.

---

## Tech stack

- **Python 3.13**, **FastAPI**, **Uvicorn**
- **LangGraph** + **LangChain** + **OpenAI** (`gpt-4o-mini`) — extraction
- **Google OR-Tools** (CP-SAT) — constraint solving
- **Graphiti** + **Neo4j** — temporal knowledge graph
- Vanilla HTML/CSS/JS frontend (no build step)

---

## Project structure

```
.
├── api_server.py          # FastAPI app — wires all three tasks together
├── langgraph_flow/        # Task 1: LangGraph extraction graph + schemas
├── or-tools-scheduler/    # Task 2: OR-Tools CP-SAT solver
├── graphiti_client/       # Task 3: Graphiti/Neo4j client + resilient wrapper
├── frontend/              # Static web UI
├── tests/                 # pytest suite (solver, models, pattern conversion)
└── docs/                  # Architecture, KG schema, Graphiti reference
```

---

## Setup

**Prerequisites:** Python 3.13, an OpenAI API key, and a Neo4j database (local or [Neo4j Aura](https://neo4j.com/cloud/aura/) free tier).

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure credentials
cp .env.example .env        # then edit .env with your real keys

# 3. Run
python api_server.py
```

Open <http://localhost:8000>.

> Pulse degrades gracefully: without Neo4j it still extracts and schedules, just
> without persistent learning. Without an OpenAI key, the OR-Tools solver and
> `/api/schedule` endpoint still work — only natural-language extraction needs it.

---

## API

| Endpoint | Purpose |
|----------|---------|
| `POST /api/extract` | Natural language -> structured tasks (multi-turn) |
| `POST /api/schedule` | Structured tasks -> optimized schedule |
| `POST /api/feedback` | Record a schedule edit for learning |
| `GET  /api/patterns/{user_id}` | Inspect learned patterns |
| `GET  /api/health` | Health check |

---

## Testing

```bash
python -m pytest tests/ -q
```

The suite covers the OR-Tools solver (no-overlap guarantees, overflow handling,
fixed-slot conflict detection, lunch insertion), input validation, and the
pattern-to-constraint conversion — all runnable without API keys.

---

## Screenshots

<!-- Add screenshots of the app here, e.g.: -->
<!-- ![Pulse Scheduler UI](docs/screenshot.png) -->
