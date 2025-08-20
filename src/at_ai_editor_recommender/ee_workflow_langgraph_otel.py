from langgraph.func import entrypoint, task
from openinference.instrumentation.langchain import LangChainInstrumentor, get_ancestor_spans, get_current_span
from openinference.instrumentation.bedrock import BedrockInstrumentor
from opentelemetry import trace as trace_api
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk import trace as trace_sdk
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.resources import Resource 
from openinference.semconv.trace import SpanAttributes, OpenInferenceSpanKindValues
from opentelemetry.trace import set_span_in_context
from opentelemetry.context import attach, detach
from dataclasses import dataclass
import boto3
import os
from dotenv import load_dotenv
from contextlib import contextmanager
from at_ai_editor_recommender.utils import load_mock_editor, llm_call
from at_ai_editor_recommender.prompts import get_editor_assignment_prompt, get_verification_prompt

load_dotenv()

endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
resource = Resource.create({"service.name": "ee-workflow-langgraph"})
tracer_provider = trace_sdk.TracerProvider(resource=resource)
trace_api.set_tracer_provider(tracer_provider)
tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint)))
# tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

tracer = trace_api.get_tracer("ee-workflow-langgraph")

@contextmanager
def start_trace(trace_name: str):
    with tracer.start_as_current_span(trace_name) as span:
        span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, OpenInferenceSpanKindValues.AGENT.value)
        yield span

# instrument both Bedrock and Langchain
BedrockInstrumentor().instrument(tracer_provider=tracer_provider)
LangChainInstrumentor().instrument(tracer_provider=tracer_provider)

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



def traced_llm_call(client, text):
    span = get_current_span()
    ctx = set_span_in_context(span)
    token = attach(ctx)  # Attach the context so child spans are linked
    try:
        msg = llm_call(client, text)  # Instrumentor will now create child span
    finally:
        detach(token)  # Clean up context
    return msg


# can be MCP service
def get_available_editors(manuscript_submission: ManuscriptSubmission):
    mock_response = load_mock_editor(1)
    return mock_response

@task
def assign_editor(editor_id: str, manuscript_submission: ManuscriptSubmission):
    return f"Editor with editor_id of {editor_id} assigned to manuscript_id: {manuscript_submission.manuscript_id}"


@task
def editor_assignment(available_editors: str):
    text = get_editor_assignment_prompt(available_editors)
    msg = traced_llm_call(client, text)
    return msg

@task
def verification(editor_assignment_result:str, available_editors:str):
    text = get_verification_prompt(editor_assignment_result, available_editors)
    msg = traced_llm_call(client, text)
    return msg


@entrypoint()
def prompt_chaining_workflow(manuscript_submission: ManuscriptSubmission):
    # No tracing
    available_editors = get_available_editors(manuscript_submission)
    editor_assignment_result = editor_assignment(available_editors).result()

    verification_result = verification(editor_assignment_result, available_editors).result()

    editor_id = "0001"
    assign_editor_result = assign_editor(editor_id, manuscript_submission).result()
    return assign_editor_result
    
    
# Invoke
def main():
    manuscript_submission = ManuscriptSubmission(
        manuscript_id="MS12345",
        coden="JAST",
        journal="Journal of Advanced Science and Technology",
        title="A Novel Approach to Quantum Computing",
        abstract="This manuscript presents a new method for quantum computation using advanced algorithms and hardware."
    )

    with start_trace("manuscript-editor-assignment"):
        for step in prompt_chaining_workflow.stream(manuscript_submission, stream_mode="updates"):
            print(step)
            print("\n")
