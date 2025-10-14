from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional
from at_ai_editor_recommender.ee_graph_claude import EditorAssignmentWorkflow, ManuscriptSubmission
import uvicorn
import logging
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv

load_dotenv()

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8012
MODEL_ID = os.getenv("MODEL_ID", "us.amazon.nova-premier-v1:0")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

class ManuscriptSubmissionRequest(BaseModel):
    manuscript_number: str
    coden: str
    # manuscript_type: str
    # manuscript_title: str
    # manuscript_abstract: str

class AssignEditorResult(BaseModel):
    editor_id: str
    assignment_result: str
    reasoning: Optional[str] = None
    expertise_factor: Optional[str] = None
    workload_factor: Optional[str] = None
    runner_up: Optional[str] = None

    class Config:
        orm_mode = True
        exclude_none = True


class WorkflowResponse(BaseModel):
    assign_editor: AssignEditorResult

workflow = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
     # Initialize workflow once
    workflow["ee"] = EditorAssignmentWorkflow(model_id=MODEL_ID)
    yield

logger = logging.getLogger(__name__)

app = FastAPI(title="Editor Assignment API", lifespan=lifespan)


@app.post("/execute_workflow", response_model=WorkflowResponse, response_model_exclude_none=True)
async def execute_workflow(submission: ManuscriptSubmissionRequest):
    try:
        manuscript_submission = ManuscriptSubmission(
            manuscript_number=submission.manuscript_number,
            coden=submission.coden
            # manuscript_type=submission.manuscript_type,
            # manuscript_title=submission.manuscript_title,
            # manuscript_abstract=submission.manuscript_abstract
        )
            
        result = await workflow["ee"].async_execute_workflow(manuscript_submission)
            
        return result
    except Exception as e:
        logger.error(f"Error executing workflow: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")

if __name__ == "__main__":
    host = os.environ.get("HOST", DEFAULT_HOST)
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    uvicorn.run(app, host=host, port=port)