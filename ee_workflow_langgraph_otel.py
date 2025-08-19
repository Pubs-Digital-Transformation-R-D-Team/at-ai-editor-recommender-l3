from langgraph.func import entrypoint, task
from openinference.instrumentation.langchain import LangChainInstrumentor
from openinference.instrumentation.bedrock import BedrockInstrumentor
from opentelemetry import trace as trace_api
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk import trace as trace_sdk
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.resources import Resource 
from dataclasses import dataclass
import boto3
import os
from dotenv import load_dotenv
from utils import load_mock_editor, llm_call
from prompts import get_editor_assignment_prompt, get_verification_prompt


load_dotenv()

endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
resource = Resource.create({"service.name": "ee-workflow-langgraph"})
tracer_provider = trace_sdk.TracerProvider(resource=resource)
trace_api.set_tracer_provider(tracer_provider)
tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint)))
# tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

# instrument both Bedrock and Langchain
BedrockInstrumentor().instrument()
LangChainInstrumentor().instrument()

MODEL_ID = 'us.amazon.nova-premier-v1:0'
MODEL_ID_VERIFICATION = 'us.amazon.nova-premier-v1:0'
SYSTEM = [{ "text": "You are a helpful assistant" }]

session = boto3.session.Session()
client = session.client('bedrock-runtime', region_name='us-east-1') 

@dataclass
class ManuscriptSubmission:
    manuscript_id: str
    coden: str
    journal: str
    title: str
    abstract: str

# can be MCP service
def get_available_editors(manuscript_submission: ManuscriptSubmission):
    mock_response = load_mock_editor(1)
    return mock_response

@task
def assign_editor(editor_id: str, manuscript_submission: ManuscriptSubmission):
    return f"Editor with editor_id of {editor_id} assigned to manuscript_id: {manuscript_submission.manuscript_id}"

@task
def editor_assignment(available_editors:str):
    text = get_editor_assignment_prompt(available_editors)
    # print("***",text)
    msg = llm_call(client, text)
    return msg

@task
def verification(editor_assignment_result:str, available_editors:str):
    text = get_verification_prompt(editor_assignment_result, available_editors)
    msg = llm_call(client, text)
    return msg


# API call: get_available_editors -> LLM (assignment)-> editor --> LLM (verify assignment) -> assign_editor
@entrypoint()
def prompt_chaining_workflow(manuscript_submission: ManuscriptSubmission):
    # API call
    available_editors = get_available_editors(manuscript_submission)
    editor_assignment_result = editor_assignment(available_editors).result()

    # use same model to verify for now
    verification_result = verification(editor_assignment_result, available_editors).result()

    # only make assign editor when verification passes
    # if verification_results ..
    editor_id = "0001"
    assign_editor_result = assign_editor(editor_id, manuscript_submission).result()
    # print(assign_editor_result)
    
    
# Invoke
manuscript_submission = ManuscriptSubmission(
    manuscript_id="MS12345",
    coden="JAST",
    journal="Journal of Advanced Science and Technology",
    title="A Novel Approach to Quantum Computing",
    abstract="This manuscript presents a new method for quantum computation using advanced algorithms and hardware."
)

for step in prompt_chaining_workflow.stream(manuscript_submission, stream_mode="updates"):
    print(step)
    print("\n")

