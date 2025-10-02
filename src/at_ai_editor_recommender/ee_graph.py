from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from typing import TypedDict, Annotated, Literal, Optional, ClassVar
from openinference.instrumentation.langchain import LangChainInstrumentor, get_current_span
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
from at_ai_editor_recommender.utils import async_llm_call, load_file
from at_ai_editor_recommender.prompts import EDITOR_ASSIGNMENT_PROMPT_TEMPLATE_V2
from at_ai_editor_recommender.editor_assignment_json_parser import EditorAssignmentJsonParser
from pathlib import Path
import aioboto3

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
    assignment_result: str | None
    reasoning: str | None
    expertise_factor: str | None
    workload_factor:str | None
    runner_up: str | None

class EditorAssignmentWorkflow:

    DEFAULT_MODEL_ID = 'us.amazon.nova-premier-v1:0'
    # MODEL_ID_VERIFICATION = 'us.amazon.nova-premier-v1:0'
    SYSTEM = [{ "text": "You are a helpful assistant" }]
    REGION_NAME = 'us-east-1'
  
    
    def __init__(self, client=None, model_id=DEFAULT_MODEL_ID, region_name=REGION_NAME):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("Initializing EditorAssignmentWorkflow")
        self._ee_url = os.getenv("EE_URL")
        self._ee_base_url = os.getenv("EE_BASE_URL")
        self._tracer = None
        self._tracer_provider = None
        self._graph: Optional[CompiledStateGraph] = None
        self._model_id = model_id
        self._region_name = region_name
        self._initialize_tracing()
        # self._client = client or self._setup_bedrock_client()
        self._session = aioboto3.Session()  
        self._graph = self._build_graph()
        self.logger.info("Done initializing EditorAssignmentWorkflow")


    def _initialize_tracing(self):
        if self._tracer is None:
            endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            resource = Resource.create({"service.name": "ee-workflow-langgraph"})
            self._tracer_provider = trace_sdk.TracerProvider(resource=resource)
            trace_api.set_tracer_provider(self._tracer_provider)
            self._tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint)))
            self._tracer = trace_api.get_tracer("ee-workflow-langgraph")
            
            # Instrument both Bedrock and Langchain
            BedrockInstrumentor().instrument(tracer_provider=self._tracer_provider)
            LangChainInstrumentor().instrument(tracer_provider=self._tracer_provider)

    

    @contextmanager
    def _start_trace(self, trace_name: str):
        with self._tracer.start_as_current_span(trace_name) as span:
            span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, OpenInferenceSpanKindValues.AGENT.value)
            yield span
    

    def _setup_bedrock_client(self):
        self.logger.info("Setting up Bedrock client with region: %s", self._region_name)
        
        # Create session with more debugging
        # session = boto3.session.Session()
        session = aioboto3.Session()
        # credentials = session.get_credentials()
        
        # # Log credential information for debugging
        # if credentials:
        #     self.logger.info(f"Found AWS credentials with access key ID: {credentials.access_key[:5]}...")
        #     self.logger.info(f"Token available: {credentials.token is not None}")
        # else:
        #     self.logger.warning("No AWS credentials detected!")
        
        # Create the client with the region
        client = session.client('bedrock-runtime', region_name=self._region_name)
        return client

    async def _traced_llm_call(self, text: str):
        span = get_current_span()
        token = attach(set_span_in_context(span))
        try:
            return await async_llm_call(
                text,
                modelId=self._model_id,
                session=self._session,             # reuse session
                region_name=self._region_name,
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
        if not self._ee_base_url:
            raise RuntimeError("Please provide EE_BASE_URL")
        url = f"{self._ee_base_url}/editor_assignment_protocol/manuscript/{manuscript_number}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json()
        return data  # { "manuscript_information": ..., "available_editors": ... }


    async def _editor_assignment(self, state):
        manuscript_submission = state["manuscript_submission"]

        manuscript_information = state["manuscript_information"]
        available_editors = state["available_editors"]

        journal_specific_rules = self._journal_specific_rules(manuscript_submission.coden)
        # prompt_template = self._prepare_prompt(manuscript_submission.coden)

        text = EDITOR_ASSIGNMENT_PROMPT_TEMPLATE_V2.format(
            journal_specific_rules=journal_specific_rules,
            manuscript_information=manuscript_information,
            available_editors=available_editors
        )

        # for tracing
        with using_prompt_template(
            template = EDITOR_ASSIGNMENT_PROMPT_TEMPLATE_V2,
            variables = {"journal_specific_rules": journal_specific_rules,
                         "manuscript_information": manuscript_information, 
                         "available_editors": available_editors},
            version = "v1.0"
        ):
            msg = await self._traced_llm_call(text)
            return {"editor_assignment_result": msg}

    async def _verification(self, state):
        editor_assignment_result = state["editor_assignment_result"]
        available_editors = state["available_editors"]

        msg = "Verification passed"
        return {"verification_result": msg}

    def extract_editor_assignment_output(self, llm_output:str):
        result = EditorAssignmentJsonParser.parse(llm_output)
        return result


    async def _assign_editor(self, state):
        manuscript_submission = state["manuscript_submission"]

        output = self.extract_editor_assignment_output(state["editor_assignment_result"])
        print(output)
        editor_id = output["selectedEditorOrcId"]
        reasoning = output["reasoning"]
        editor_person_id = output["selectedEditorPersonId"]
        filtered_out_editors = output["filteredOutEditors"]
        # expertise_factor = output.get("Expertise Factor", "")
        # expertise_factor = output["Expertise Factor"]
        # workload_factor = output["Workload Factor"]

        runner_up = output["runnerUp"]

        result = f"Editor with editor_id of {editor_id} assigned to manuscript_number: {manuscript_submission.manuscript_number}"
        return {"editor_id": editor_id, 
                "editor_person_id": editor_person_id,
                "assignment_result": result, 
                "reasoning": reasoning,
                "filtered_out_editors": filtered_out_editors,
                "runner_up": runner_up}

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
           

