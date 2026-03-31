"""
FastAPI app — POST /execute_workflow with L3 memory.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agent import EditorAssignmentAgent, ManuscriptSubmission
from memory import create_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MODEL_ID = os.getenv("MODEL_ID", "us.amazon.nova-premier-v1:0")
_agent = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = None
    if os.getenv("POSTGRES_URI"):
        try:
            store = await create_store()
        except Exception as e:
            logger.warning("L3 memory init failed: %s", e)
    _agent["ee"] = EditorAssignmentAgent(store=store, model_id=MODEL_ID)
    logger.info("Agent ready (model=%s, memory=%s)", MODEL_ID, "ON" if store else "OFF")
    yield


app = FastAPI(title="Editor Assignment — Memory POC", lifespan=lifespan)


class WorkflowRequest(BaseModel):
    manuscript_number: str
    journal_id: str
    is_resubmit: bool = False


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/execute_workflow")
async def execute_workflow(req: WorkflowRequest):
    try:
        ms = ManuscriptSubmission(req.manuscript_number, req.journal_id, req.is_resubmit)
        result = await _agent["ee"].execute(ms)
        return {"data": result}
    except Exception as e:
        logger.error("Workflow failed: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})

