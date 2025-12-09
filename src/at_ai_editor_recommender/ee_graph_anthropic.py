from unittest import result
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from typing import TypedDict, Annotated, Literal, Optional, ClassVar
from openinference.instrumentation.langchain import LangChainInstrumentor, get_current_span
from openinference.instrumentation.anthropic import AnthropicInstrumentor
from openinference.instrumentation.bedrock import BedrockInstrumentor
from openinference.instrumentation import using_prompt_template
from opentelemetry import trace as trace_api
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk import trace as trace_sdk
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.resources import Resource 
from openinference.semconv.trace import SpanAttributes, OpenInferenceSpanKindValues
from opentelemetry.trace import set_span_in_context
from opentelemetry.context import attach, detach
from dataclasses import dataclass
import boto3
import os
import asyncio
import logging
import aiohttp
from dotenv import load_dotenv
from contextlib import contextmanager
from at_ai_editor_recommender.utils import load_file, anthropic_llm_call
from at_ai_editor_recommender.prompts import EDITOR_ASSIGNMENT_PROMPT_TEMPLATE_V3
from at_ai_editor_recommender.editor_assignment_json_parser import EditorAssignmentJsonParser
from at_ai_editor_recommender.ee_api_adapter import get_adapter_for_url
from pathlib import Path
# import aioboto3
from anthropic import AsyncAnthropicBedrock

load_dotenv()

@dataclass
class ManuscriptSubmission:
    manuscript_number: str
    coden: str
    # manuscript_type: str
    # manuscript_title: str
    # manuscript_abstract: str

# Define the state schema
class State(TypedDict):
    manuscript_submission: ManuscriptSubmission
    manuscript_information: str | None
    available_editors: str | None
    editor_assignment_result: str | None
    verification_result: str | None
    editor_id: str | None
    editor_person_id: str | None
    assignment_result: str | None
    reasoning: str | None
    expertise_factor: str | None
    workload_factor:str | None
    runner_up: str | None
    filtered_out_editors: str | None

class EditorAssignmentWorkflow:

    DEFAULT_MODEL_ID = 'us.amazon.nova-premier-v1:0'
    # MODEL_ID_VERIFICATION = 'us.amazon.nova-premier-v1:0'
    SYSTEM = [{ "text": "You are a helpful assistant" }]
    REGION_NAME = 'us-east-1'
  
    # Verification status constants
    VERIFICATION_PASSED = "Verification passed"
    VERIFICATION_FAILED = "Verification failed"

    def __init__(self, client=None, model_id=DEFAULT_MODEL_ID, region_name=REGION_NAME):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("Initializing EditorAssignmentWorkflow")
        self.logger.info("Using model_id: %s", model_id)
        self._ee_url = os.getenv("EE_URL")
        self.logger.info("Using EE API: %s", self._ee_url)
        self._assign_url = os.getenv("ASSIGN_URL")
        self.logger.info("Using Assign API: %s", self._assign_url)
        # self._ee_base_url = os.getenv("EE_BASE_URL")
        self._tracer = None
        self._tracer_provider = None
        self._graph: Optional[CompiledStateGraph] = None
        self._model_id = model_id
        self._region_name = region_name
        self._initialize_tracing()
        self._client = client or self._setup_bedrock_client()
        # self._session = aioboto3.Session()  
        self._graph = self._build_graph()
        self.logger.info("Done initializing EditorAssignmentWorkflow")


    def _initialize_tracing(self):
        if self._tracer is None:
            endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            self.logger.info("Setting up OpenTelemetry tracing with OTLP endpoint: %s", endpoint)
            resource = Resource.create({"service.name": "ee-workflow-langgraph"})
            self._tracer_provider = trace_sdk.TracerProvider(resource=resource)
            trace_api.set_tracer_provider(self._tracer_provider)
            self._tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint)))
            self._tracer = trace_api.get_tracer("ee-workflow-langgraph")
            
            # Instrument both Bedrock and LangGraph
            AnthropicInstrumentor().instrument(tracer_provider=self._tracer_provider)
            LangChainInstrumentor().instrument(tracer_provider=self._tracer_provider)

    

    @contextmanager
    def _start_trace(self, trace_name: str):
        with self._tracer.start_as_current_span(trace_name) as span:
            span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, OpenInferenceSpanKindValues.AGENT.value)
            yield span
    



    def _setup_bedrock_client(self):
        self.logger.info("Setting up Anthropic Bedrock client with region: %s", self._region_name)
        

        client = AsyncAnthropicBedrock(
            # default_headers={
            #     "Proxy-Authorization": f"Bearer {os.getenv('AWS_BEARER_TOKEN_BEDROCK')}"
            # },
            # aws_region=self._region_name,
            aws_region="us-east-1"
            # aws_session_token=bearer_token
        )
        return client

    async def _traced_llm_call(self, text: str):
        span = get_current_span()
        token = attach(set_span_in_context(span))
        try:
            return await anthropic_llm_call(
                client=self._client,
                text=text,
                modelId=self._model_id
            )
        finally:
            detach(token)

    def _journal_specific_rules(self, coden):

        # Assume the project root is one directory above src
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
        prompts_root = os.path.join(project_root, "prompts")
        
        journal_specific_rules_default = os.path.join(prompts_root, "journal_specific_rules", "DEFAULT.md")
        journal_specific_rules_path = os.path.join(prompts_root, "journal_specific_rules", f"{coden}.md")

        if os.path.exists(journal_specific_rules_path):
            journal_specific_rules = load_file(journal_specific_rules_path)
            self.logger.info(f"Loaded journal specific rules from {journal_specific_rules_path}")
        else:
            # Fallback to default
            journal_specific_rules = load_file(journal_specific_rules_default)
            self.logger.info(f"Loaded default rules from {journal_specific_rules_default}")

        return journal_specific_rules

    async def _get_manuscript_with_editors(self, state):
        """
        Fetch manuscript information and available editors in a single API call.
        """
        manuscript_submission = state["manuscript_submission"]
        manuscript_number = manuscript_submission.manuscript_number
        journal_id = manuscript_submission.coden
        adapter = get_adapter_for_url(self._ee_url)
        self.logger.info(f"Using adapter: {adapter.__class__.__name__} for URL: {self._ee_url}")
        result = await adapter.get_manuscript_with_editors(manuscript_number, journal_id)
        self.logger.info(f"Fetched manuscript and editors for manuscript_number: {manuscript_number}, journal_id: {journal_id}")
        
        return result  # { "manuscript_information": ..., "available_editors": ...

    # async def _get_manuscript_with_editors(self, state):
    #     """
    #     Fetch manuscript information and available editors in a single API call.
    #     """
    #     manuscript_submission = state["manuscript_submission"]
    #     manuscript_number = manuscript_submission.manuscript_number
    #     if not self._ee_base_url:
    #         raise RuntimeError("Please provide EE_BASE_URL")
    #     url = f"{self._ee_base_url}/editor_assignment_protocol/manuscript/{manuscript_number}"
    #     async with aiohttp.ClientSession() as session:
    #         async with session.get(url) as resp:
    #             resp.raise_for_status()
    #             data = await resp.json()
    #     return data  # { "manuscript_information": ..., "available_editors": ... }


    async def _editor_assignment(self, state):
        manuscript_submission = state["manuscript_submission"]

        manuscript_information = state["manuscript_information"]
        available_editors = state["available_editors"]

        journal_specific_rules = self._journal_specific_rules(manuscript_submission.coden)
        # prompt_template = self._prepare_prompt(manuscript_submission.coden)

        text = EDITOR_ASSIGNMENT_PROMPT_TEMPLATE_V3.format(
            journal_specific_rules=journal_specific_rules,
            manuscript_information=manuscript_information,
            available_editors=available_editors
        )

        # for tracing
        with using_prompt_template(
            template = EDITOR_ASSIGNMENT_PROMPT_TEMPLATE_V3,
            variables = {"journal_specific_rules": journal_specific_rules,
                         "manuscript_information": manuscript_information, 
                         "available_editors": available_editors},
            version = "v1.0"
        ):
            msg = await self._traced_llm_call(text)
            return {"editor_assignment_result": msg}

    # async def _verification(self, state):
    #     editor_assignment_result = state["editor_assignment_result"]
    #     available_editors = state["available_editors"]

    #     msg = "Verification passed"
    #     return {"verification_result": msg}


    async def _verification(self, state):
        editor_assignment_result = state["editor_assignment_result"]
        output = EditorAssignmentWorkflow._extract_editor_assignment_output(editor_assignment_result)

        has_editor = bool(output.get("selectedEditorPersonId", ""))
        
        # Just add a verification flag to state rather than changing the flow
        if has_editor:
            return {"verification_result": self.VERIFICATION_PASSED}
        else:
            return {"verification_result": self.VERIFICATION_FAILED}


    @staticmethod
    def _extract_editor_assignment_output(llm_output:str):
        parsed_result = EditorAssignmentJsonParser.parse(llm_output)
        return parsed_result

    async def _assign_editor(self, state):
        manuscript_submission = state["manuscript_submission"]
        verification_result = state.get("verification_result", "")

        llm_response = EditorAssignmentWorkflow._extract_editor_assignment_output(state["editor_assignment_result"])
        self.logger.info("Editor assignment result: %s", llm_response)

        if verification_result == self.VERIFICATION_FAILED:
            assignment_result = f"No editor assigned to manuscript_number: {manuscript_submission.manuscript_number}"
            return EditorAssignmentWorkflow._make_assignment_response(llm_response, assignment_result)


        # Make the actual API call to assign the editor
        await self._call_assign_api(manuscript_submission, llm_response.get("selectedEditorPersonId", ""))

        assignment_result = f"Editor with editor_id of {llm_response.get("selectedEditorPersonId", "")} assigned to manuscript_number: {manuscript_submission.manuscript_number}"
        return EditorAssignmentWorkflow._make_assignment_response(llm_response, assignment_result)

    @staticmethod
    def _make_assignment_response(output, assignment_result):
        return {
            "editor_id": output.get("selectedEditorOrcId", ""),
            "editor_person_id": output.get("selectedEditorPersonId", ""),
            "assignment_result": assignment_result,
            "reasoning": output.get("reasoning", ""),
            "filtered_out_editors": output.get("filteredOutEditors", []),
            "runner_up": output.get("runnerUp", "")
        }

    async def _call_assign_api(self, manuscript_submission, editor_id):
        """Make the API call to assign the editor."""
        if not self._assign_url:
            raise RuntimeError("Please provide ASSIGN_URL environment variable")

        self.logger.info(f"Assigning editor with API call to {self._assign_url}")

        async with aiohttp.ClientSession() as session:
            form_data = aiohttp.FormData()
            form_data.add_field('manuscript_id', manuscript_submission.manuscript_number)
            form_data.add_field('journal_id', manuscript_submission.coden)
            form_data.add_field('editor_id', editor_id)

            async with session.post(self._assign_url, data=form_data) as resp:
                try:
                    resp.raise_for_status()
                    api_response = await resp.text()
                    self.logger.info(f"Assign API response: {api_response}")
                except aiohttp.ClientResponseError as e:
                    response_body = await resp.text()
                    e.response_text = response_body
                    raise

        self.logger.info(
            f"Successfully assigned editor: Editor with ID {editor_id} assigned to manuscript {manuscript_submission.manuscript_number}")


    def _build_graph(self):
        graph = StateGraph(State)
        graph.add_node("get_manuscript_with_editors", self._get_manuscript_with_editors)
        graph.add_node("editor_assignment", self._editor_assignment)
        graph.add_node("verification", self._verification)
        graph.add_node("assign_editor", self._assign_editor)
        
        graph.add_edge(START, "get_manuscript_with_editors")
        graph.add_edge("get_manuscript_with_editors", "editor_assignment")
        graph.add_edge("editor_assignment", "verification")
        graph.add_edge("verification", "assign_editor")
        graph.add_edge("assign_editor", END)

        return graph.compile()

    async def _run(self, manuscript_submission):
        initial_state = {"manuscript_submission": manuscript_submission}
        return self._graph.ainvoke(initial_state)

        
    async def _astream(self, manuscript_submission):
        initial_state = {"manuscript_submission": manuscript_submission}
        async for item in self._graph.astream(initial_state):
            yield item

    async def async_execute_workflow(self, manuscript_submission):
        with self._start_trace("manuscript-editor-assignment"):
            final_state = None
            async for step in self._astream(manuscript_submission):
                logging.info(step)
                final_state = step
            return final_state
           

