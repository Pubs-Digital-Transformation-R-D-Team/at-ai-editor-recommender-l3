import re
from urllib import response
from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from typing import TypedDict, Annotated, Literal, Optional, ClassVar
from openinference.instrumentation.langchain import LangChainInstrumentor, get_current_span
from openinference.instrumentation.bedrock import BedrockInstrumentor
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
from at_ai_editor_recommender.utils import load_mock_editor, llm_call, async_llm_call
from at_ai_editor_recommender.prompts import get_editor_assignment_prompt, get_verification_prompt

load_dotenv()

@dataclass
class ManuscriptSubmission:
    manuscript_number: str
    coden: str
    manuscript_type: str
    manuscript_title: str
    manuscript_abstract: str

# Define the state schema
class State(TypedDict):
    manuscript_submission: ManuscriptSubmission
    available_editors: str | None
    editor_assignment_result: str | None
    verification_result: str | None
    editor_id: str | None
    assignment_result: str | None

class EditorAssignmentWorkflow:

    DEFAULT_MODEL_ID = 'us.amazon.nova-premier-v1:0'
    # MODEL_ID_VERIFICATION = 'us.amazon.nova-premier-v1:0'
    SYSTEM = [{ "text": "You are a helpful assistant" }]
    REGION_NAME = 'us-east-1'
  
    
    def __init__(self, client=None, model_id=DEFAULT_MODEL_ID, region_name=REGION_NAME):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("Initializing EditorAssignmentWorkflow")
        self._ee_url = os.getenv("EE_URL")
        self._tracer = None
        self._tracer_provider = None
        self._graph: Optional[CompiledStateGraph] = None
        self._model_id = model_id
        self._region_name = region_name
        self._initialize_tracing()
        self._client = client or self._setup_bedrock_client()
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
        session = boto3.session.Session()
        return session.client('bedrock-runtime', region_name=self._region_name)

    async def _traced_llm_call(self, text):
        span = get_current_span()
        ctx = set_span_in_context(span)
        token = attach(ctx)
        try:
            msg = await async_llm_call(self._client, text, modelId=self._model_id)
        finally:
            detach(token)
        return msg

    async def _get_available_editors(self, state):
        manuscript_submission = state["manuscript_submission"]
        manuscript_number = manuscript_submission.manuscript_number
        if not self._ee_url:
            raise RuntimeError("Please provide EE_URL")
        url = f"{self._ee_url}?manuscript={manuscript_number}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json()
        return {"available_editors": data}

    async def _editor_assignment(self, state):
        available_editors = state["available_editors"]
        text = get_editor_assignment_prompt(available_editors)
        msg = await self._traced_llm_call(text)
        return {"editor_assignment_result": msg}

    async def _verification(self, state):
        editor_assignment_result = state["editor_assignment_result"]
        available_editors = state["available_editors"]
        text = get_verification_prompt(editor_assignment_result, available_editors)
        msg = await self._traced_llm_call(text)
        return {"verification_result": msg}

    def extract_selected_editor(self, response: str) -> str | None:
        match = re.search(r"Selected Editor:\s*([A-Z0-9\-X]+)", response, re.IGNORECASE)
        if match:
            return match.group(1)
        return None


    async def _assign_editor(self, state):
        manuscript_submission = state["manuscript_submission"]
        # editor_id = "0001"
        editor_id = self.extract_selected_editor(state["editor_assignment_result"]) 
        result = f"Editor with editor_id of {editor_id} assigned to manuscript_number: {manuscript_submission.manuscript_number}"
        return {"editor_id": editor_id, "assignment_result": result}

    def _build_graph(self):
        graph = StateGraph(State)

        graph.add_node("get_available_editors", self._get_available_editors)
        graph.add_node("editor_assignment", self._editor_assignment)
        graph.add_node("verification", self._verification)
        graph.add_node("assign_editor", self._assign_editor)
        
        graph.add_edge(START, "get_available_editors")
        graph.add_edge("get_available_editors", "editor_assignment")
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
           

async def main():

    manuscript_submission = ManuscriptSubmission(
        manuscript_number="jm-2024-02780t",
        coden="jmcmar",
        # journal="Journal of Advanced Science and Technology",
        manuscript_type="Article",
        manuscript_title="Investigation of the ameliorative effects of amygdalin against arsenic trioxide-induced cardiac toxicity in rat",
        manuscript_abstract="Amygdalin, recognized as vitamin B17, is celebrated for its antioxidant and anti-inflammatory prowess, which underpins its utility in averting disease and decelerating the aging process. This study ventures to elucidate the cardioprotective mechanisms of amygdalin against arsenic trioxide (ATO)-induced cardiac injury, with a spotlight on the AMP-activated protein kinase (AMPK) and sirtuin-1 (SIRT1) signaling cascade. Employing a Sprague-Dawley rat model, we administered amygdalin followed by ATO and conducted a 15-day longitudinal study. Our findings underscore the ameliorative impact of amygdalin on histopathological cardiac anomalies, a reduction in cardiac biomarkers, and an invigoration of antioxidant defenses, thereby attenuating oxidative stress and inflammation. Notably, amygdalin's intervention abrogated ATO-induced apoptosis and inflammatory cascades, modulating key proteins along the AMPK/SIRT1 pathway and significantly dampening inflammation. Collectively, these insights advocate for amygdalin's role as a guardian against ATO-induced cardiotoxicity, potentially through the activation of the AMPK/SIRT1 axis, offering a novel therapeutic vista in mitigating oxidative stress, apoptosis, and inflammation."
    )

    workflow = EditorAssignmentWorkflow()
    await workflow.async_execute_workflow(manuscript_submission)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    asyncio.run(main())