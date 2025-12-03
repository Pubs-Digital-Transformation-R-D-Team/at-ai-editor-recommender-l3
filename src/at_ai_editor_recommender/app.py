from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any, Optional, Union
from at_ai_editor_recommender.ee_graph_anthropic import EditorAssignmentWorkflow, ManuscriptSubmission
import uvicorn
import logging
from contextlib import asynccontextmanager
import os
import aiohttp
import json
from dotenv import load_dotenv

load_dotenv()

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8012
MODEL_ID = os.getenv("MODEL_ID", "us.amazon.nova-premier-v1:0")

# Error constants
ERROR_CODE_DOWNSTREAM_API = "DOWNSTREAM_API_ERROR"
ERROR_CODE_CONNECTION = "DOWNSTREAM_API_CONNECTION_ERROR"
ERROR_CODE_WORKFLOW = "WORKFLOW_EXECUTION_ERROR"

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


class SuccessResponse(BaseModel):
    data: AssignEditorResult

class ErrorResponse(BaseModel):
    data: Optional[Any] = None
    errorCode: str
    errorMessage: str

class WorkflowResponse(BaseModel):
    assign_editor: AssignEditorResult

# Union response type for the API
ApiResponse = Union[SuccessResponse, ErrorResponse]

workflow = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
     # Initialize workflow once
    workflow["ee"] = EditorAssignmentWorkflow(model_id=MODEL_ID)
    yield

logger = logging.getLogger(__name__)

app = FastAPI(title="Editor Assignment API", lifespan=lifespan)


def _extract_error_details(exception: aiohttp.ClientResponseError) -> tuple[str, str]:
    """Extract error code and message from ClientResponseError JSON response.

    Returns:
        tuple[str, str]: (error_code, error_message)
    """
    error_message = exception.message
    error_code = ERROR_CODE_DOWNSTREAM_API

    try:
        if hasattr(exception, 'text') and exception.text:
            response_data = json.loads(exception.text)
            error_message = response_data['data']['errorDetails']
            error_code = response_data['data']['errorCode']
    except (json.JSONDecodeError, KeyError, AttributeError, TypeError) as parse_error:
        logger.warning(f"Could not parse error response JSON: {parse_error}")
        # Keep the original error message if JSON parsing fails

    logger.error(f"Downstream API error: Code {error_code}, Message: {error_message}")
    return error_code, error_message


@app.post("/execute_workflow", response_model=ApiResponse, response_model_exclude_none=True)
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

        return SuccessResponse(data=result.assign_editor)

    except aiohttp.ClientResponseError as e:
        # Handle HTTP errors from EE API and forward the status code
        error_code, error_message = _extract_error_details(e)
        error_response = ErrorResponse(
            errorCode=error_code,
            errorMessage=error_message
        )
        return JSONResponse(status_code=e.status, content=error_response.model_dump())

    except aiohttp.ClientError as e:
        # Handle other aiohttp errors (connection errors, etc.)
        logger.error(f"Downstream API connection error: {str(e)}")
        error_response = ErrorResponse(
            errorCode=ERROR_CODE_CONNECTION,
            errorMessage=f"Failed to connect to Downstream API: {str(e)}"
        )
        return JSONResponse(status_code=502, content=error_response.model_dump())

    except Exception as e:
        logger.error(f"Error executing workflow: {str(e)}")
        error_response = ErrorResponse(
            errorCode=ERROR_CODE_WORKFLOW,
            errorMessage=f"Workflow execution failed: {str(e)}"
        )
        return JSONResponse(status_code=500, content=error_response.model_dump())

if __name__ == "__main__":
    host = os.environ.get("HOST", DEFAULT_HOST)
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    uvicorn.run(app, host=host, port=port)