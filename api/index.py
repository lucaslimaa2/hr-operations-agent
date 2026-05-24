"""
FastAPI app — HTTP surface for the HR Operations Agent.

Endpoints:
  - GET  /api/ping              health check
  - POST /api/chat              non-streaming, returns full JSON response
  - POST /api/chat/stream       SSE stream of {classifier, tool_use, tool_result,
                                 text_delta, done, error} events

The streaming endpoint is what the UI uses. The non-streaming endpoint exists
for programmatic consumers (curl, scripts) where streaming is overkill.

Deploy notes:
  - On Vercel: serverless Python function. Cold starts include the MCP
    subprocess spawn — expect ~2s first request, faster thereafter.
  - CORS is open in development (vanilla HTML/JS UI served from same origin
    in production but opened locally during dev).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.orchestrator import OrchestratorResponse, run, run_stream

app = FastAPI(
    title="HR Operations Agent",
    description="Multi-agent HR ops system over MCP. See https://github.com/...",
    version="0.1.0",
)

# CORS — open during dev. Tighten before any sensitive deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# =============================================================================
# Schemas
# =============================================================================


class ChatRequest(BaseModel):
    message: str = Field(..., description="The user's natural-language HR request.")
    session_id: str | None = Field(
        default=None,
        description="Optional chat session ID. Generated if omitted.",
    )


class PingResponse(BaseModel):
    status: str
    service: str = "hr-operations-agent"


# =============================================================================
# Endpoints
# =============================================================================


@app.get("/api/ping", response_model=PingResponse)
async def ping() -> PingResponse:
    """Health check. Used by uptime monitors and the smoke test."""
    return PingResponse(status="ok")


@app.post("/api/chat", response_model=OrchestratorResponse)
async def chat(req: ChatRequest) -> OrchestratorResponse:
    """Run a request synchronously and return the full response as JSON.

    Use /api/chat/stream for token-by-token streaming (what the UI uses).
    """
    return await run(req.message, session_id=req.session_id)


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE stream of orchestrator events.

    Each line is `data: <json>\\n\\n`. Event types:
      - classifier   routing decision (which agents will be invoked)
      - tool_use     a tool call is about to fire
      - tool_result  the tool returned
      - text_delta   Sonnet token(s)
      - done         final metadata (cost, session_id, agents_invoked)
      - error        terminal error
    """

    async def event_source() -> Any:
        async for event in run_stream(req.message, session_id=req.session_id):
            # SSE wire format: data: <json>\n\n
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if behind one
            "Connection": "keep-alive",
        },
    )
