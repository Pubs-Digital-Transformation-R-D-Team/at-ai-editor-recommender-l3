from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional
from at_ai_editor_recommender.ee_graph_async_eeapi import EditorAssignmentWorkflow, ManuscriptSubmission
import uvicorn
import logging
from contextlib import asynccontextmanager


class ManuscriptSubmissionRequest(BaseModel):
    manuscript_number: str
    coden: str
    manuscript_type: str
    manuscript_title: str
    manuscript_abstract: str

class AssignEditorResult(BaseModel):
    editor_id: str
    assignment_result: str

class WorkflowResponse(BaseModel):
    assign_editor: AssignEditorResult

workflow = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
     # Initialize workflow once
    workflow["ee"] = EditorAssignmentWorkflow()
    yield

app = FastAPI(title="Editor Assignment API", lifespan=lifespan)


@app.post("/execute_workflow", response_model=WorkflowResponse)
async def execute_workflow(submission: ManuscriptSubmissionRequest):
    try:
        manuscript_submission = ManuscriptSubmission(
            manuscript_number=submission.manuscript_number,
            coden=submission.coden,
            manuscript_type=submission.manuscript_type,
            manuscript_title=submission.manuscript_title,
            manuscript_abstract=submission.manuscript_abstract
        )
            
        result = await workflow["ee"].async_execute_workflow(manuscript_submission)
            
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    uvicorn.run(app, host="0.0.0.0", port=8011)