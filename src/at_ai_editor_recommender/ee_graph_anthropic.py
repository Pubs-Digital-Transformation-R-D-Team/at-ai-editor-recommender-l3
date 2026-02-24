import json

from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from typing import TypedDict, Annotated, Literal, Optional, ClassVar
from dataclasses import dataclass
import os
import logging
import aiohttp
from dotenv import load_dotenv
from at_ai_editor_recommender.utils import load_file, anthropic_llm_call
from at_ai_editor_recommender.prompts import EDITOR_ASSIGNMENT_PROMPT_TEMPLATE_V3
from at_ai_editor_recommender.editor_assignment_json_parser import EditorAssignmentJsonParser
from at_ai_editor_recommender.ee_api_adapter import get_adapter_for_url
from at_ai_editor_recommender.memory import save_assignment_to_memory, search_similar_assignments, format_past_assignments_for_prompt
from anthropic import AsyncAnthropicBedrock

load_dotenv()

@dataclass
class ManuscriptSubmission:
    manuscript_number: str
    journal_id: str
    is_resubmit: bool

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
    is_resubmit: bool | None
    is_assignment_valid: bool | None
    existing_assigned_editor: str | None

class EditorAssignmentWorkflow:

    DEFAULT_MODEL_ID = 'us.amazon.nova-premier-v1:0'
    REGION_NAME = 'us-east-1'
  
    # Verification status constants
    VERIFICATION_PASSED = "Verification passed"
    VERIFICATION_FAILED = "Verification failed"

    def __init__(self, client=None, model_id=DEFAULT_MODEL_ID, region_name=REGION_NAME,
                 checkpointer=None, store=None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("Initializing EditorAssignmentWorkflow")
        self.logger.info("Using model_id: %s", model_id)
        self._ee_url = os.getenv("EE_URL")
        self.logger.info("Using EE API: %s", self._ee_url)
        self._assign_url = os.getenv("ASSIGN_URL")
        self.logger.info("Using Assign API: %s", self._assign_url)
        self.validate_assignment_url = os.getenv("VALIDATE_ASSIGNMENT_URL")
        self.logger.info("Using Validate Assignment API: %s", self.validate_assignment_url)
        self._graph: Optional[CompiledStateGraph] = None
        self._model_id = model_id
        self._region_name = region_name
        self._client = client or self._setup_bedrock_client()

        # ── Memory (Tier 2: Session, Tier 3: Long-term) ──────────────────
        self._checkpointer = checkpointer   # Postgres checkpointer for session memory
        self._store = store                 # Postgres store for long-term memory

        self._graph = self._build_graph()
        self.logger.info("EditorAssignmentWorkflow Initialized successfully")
        if checkpointer:
            self.logger.info("Session Memory (checkpointer) is ENABLED")
        if store:
            self.logger.info("Long-term Memory (store) is ENABLED")


    def _setup_bedrock_client(self):
        self.logger.info("Setting up Anthropic Bedrock client with region: %s", self._region_name)
        client = AsyncAnthropicBedrock(
            aws_region=self._region_name
        )
        return client



    def _resolve_journal_specific_rules(self, journal_id):

        # Assume the project root is one directory above src
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
        prompts_root = os.path.join(project_root, "prompts")
        
        journal_specific_rules_default = os.path.join(prompts_root, "journal_specific_rules", "DEFAULT.md")
        journal_specific_rules_path = os.path.join(prompts_root, "journal_specific_rules", f"{journal_id}.md")

        if os.path.exists(journal_specific_rules_path):
            journal_specific_rules = load_file(journal_specific_rules_path)
            self.logger.info(f"Loaded journal specific rules from {journal_specific_rules_path}")
        else:
            # Fallback to default
            journal_specific_rules = load_file(journal_specific_rules_default)
            self.logger.info(f"Loaded default rules from {journal_specific_rules_default}")

        return journal_specific_rules

    @staticmethod
    async def _check_resubmission_status(state):
        """
        Check if the manuscript is a resubmission.
        """
        manuscript_submission = state["manuscript_submission"]

        return {"is_resubmit": manuscript_submission.is_resubmit}


    async  def _validate_existing_assignment(self, state):
        """
        Validate the editor assignment using an external API.
        """
        if not self.validate_assignment_url:
            raise RuntimeError("Please provide VALIDATE_ASSIGNMENT_URL environment variable")

        manuscript_submission = state["manuscript_submission"]
        self.logger.info(f"Validating editor assignment for manuscript_number: {manuscript_submission.manuscript_number}")

        async with aiohttp.ClientSession() as session:
            form_data = aiohttp.FormData()
            form_data.add_field('manuscript_id', manuscript_submission.manuscript_number)
            form_data.add_field('journal_id', manuscript_submission.journal_id)

            async with session.post(self.validate_assignment_url, data=form_data) as resp:
                try:
                    resp.raise_for_status()
                    api_response = await resp.json()
                    self.logger.info(f"Validation API response: {api_response}")
                except aiohttp.ClientResponseError as e:
                    response_body = await resp.text()
                    e.response_text = response_body
                    raise


        return {
            "is_assignment_valid": api_response.get("data", {}).get("valid", False),
            "existing_assigned_editor": api_response.get("data", {}).get("editorId", "")
        }

    async def _fetch_manuscript_data(self, state):
        """
        Fetch manuscript information and available editors in a single API call.
        """
        manuscript_submission = state["manuscript_submission"]
        manuscript_number = manuscript_submission.manuscript_number
        journal_id = manuscript_submission.journal_id
        adapter = get_adapter_for_url(self._ee_url)
        self.logger.info(f"Using adapter: {adapter.__class__.__name__} for URL: {self._ee_url}")
        result = await adapter.get_manuscript_with_editors(manuscript_number, journal_id)
        self.logger.info(f"Fetched manuscript and editors for manuscript_number: {manuscript_number}, journal_id: {journal_id}")
        
        return result


    async def _generate_editor_recommendation(self, state):
        manuscript_submission = state["manuscript_submission"]
        manuscript_information = state["manuscript_information"]
        available_editors = state["available_editors"]
        journal_specific_rules = self._resolve_journal_specific_rules(manuscript_submission.journal_id)

        # ── Long-term Memory READ: search for similar past assignments ────
        past_assignments_text = ""
        if self._store:
            try:
                # Use manuscript_information as the search query — it contains
                # title, abstract, keywords which are the best semantic signal
                query = (manuscript_information or "")[:1000]  # Cap at 1000 chars for search
                if query.strip():
                    similar = await search_similar_assignments(
                        self._store,
                        query=query,
                        journal_id=manuscript_submission.journal_id,
                        limit=5,
                    )
                    past_assignments_text = format_past_assignments_for_prompt(similar)
                    if past_assignments_text:
                        self.logger.info(
                            "Long-term Memory: injecting %d similar past assignments into prompt",
                            len(similar),
                        )
                    else:
                        self.logger.info("Long-term Memory: no similar past assignments found")
            except Exception as e:
                # Never let memory reads break the main workflow
                self.logger.warning("Long-term Memory search failed (continuing without): %s", e)

        # Build the prompt — with or without past assignment context
        text = EDITOR_ASSIGNMENT_PROMPT_TEMPLATE_V3.format(
            journal_specific_rules=journal_specific_rules,
            manuscript_information=manuscript_information,
            available_editors=available_editors,
            past_assignments=past_assignments_text,
        )

        msg = await anthropic_llm_call(
            client=self._client,
            text=text,
            modelId=self._model_id)

        return {"editor_assignment_result": msg}


    async def _verify_recommendation(self, state):
        editor_assignment_result = state["editor_assignment_result"]
        output = EditorAssignmentWorkflow._extract_editor_assignment_output(editor_assignment_result)

        has_editor = bool(output.get("selectedEditorPersonId", ""))

        if has_editor:
            return {"verification_result": self.VERIFICATION_PASSED}
        else:
            return {"verification_result": self.VERIFICATION_FAILED}


    def _should_assign_editor(self, state):
        verification_result = state.get("verification_result", "")
        if verification_result == self.VERIFICATION_PASSED:
            return "assign"
        else:
            return "skip"

    @staticmethod
    def _route_after_resubmission_check(state):
        """Route based on resubmission status"""
        is_resubmit = state.get("is_resubmit", False)
        if is_resubmit:
            return "resubmission_flow"
        else:
            return "normal_flow"

    @staticmethod
    def _route_after_assignment_validation(state):
        """Route based on assignment validation result"""
        is_assignment_valid = state.get("is_assignment_valid", False)
        if is_assignment_valid:
            return "valid_assignment"
        else:
            return "invalid_assignment"

    @staticmethod
    def _extract_editor_assignment_output(llm_output:str):
        parsed_result = EditorAssignmentJsonParser.parse(llm_output)
        return parsed_result

    async def _skip_assignment(self, state):
        manuscript_submission = state["manuscript_submission"]
        llm_response = EditorAssignmentWorkflow._extract_editor_assignment_output(state["editor_assignment_result"])
        self.logger.info("Editor assignment result: %s", llm_response)

        # ── Long-term Memory WRITE (record the skip decision too) ──
        await self._save_to_long_term_memory(manuscript_submission, llm_response)

        assignment_result = f"No editor assigned to manuscript_number: {manuscript_submission.manuscript_number}"
        return EditorAssignmentWorkflow._make_assignment_response(llm_response, assignment_result)


    @staticmethod
    async def _use_existing_assignment(state):
        """Handle case where valid editor is already assigned (resubmission)"""
        manuscript_submission = state["manuscript_submission"]
        existing_assigned_editor = state["existing_assigned_editor"]
        assignment_result = f"Valid editor is already assigned to manuscript_number: {manuscript_submission.manuscript_number}, editor_id: {existing_assigned_editor}"

        # Create a response indicating existing assignment
        return {
            "editor_id": "",
            "editor_person_id": existing_assigned_editor,
            "assignment_result": assignment_result,
            "reasoning": "Manuscript is a resubmission with valid existing editor assignment",
            "filtered_out_editors": "",
            "runner_up": ""
        }

    async def _execute_assignment(self, state):
        manuscript_submission = state["manuscript_submission"]
        llm_response = EditorAssignmentWorkflow._extract_editor_assignment_output(state["editor_assignment_result"])
        self.logger.info("Editor assignment result: %s", llm_response)

        # ── Long-term Memory WRITE (before API call so data is saved even on failure) ──
        await self._save_to_long_term_memory(manuscript_submission, llm_response)

        # Make the actual API call to assign the editor
        await self._call_assign_api(manuscript_submission, llm_response.get("selectedEditorPersonId", ""), state)

        assignment_result = f"Editor with editor_id of {llm_response.get("selectedEditorPersonId", "")} assigned to manuscript_number: {manuscript_submission.manuscript_number}"
        return EditorAssignmentWorkflow._make_assignment_response(llm_response, assignment_result)

    @staticmethod
    def _make_assignment_response(output, assignment_result):
        return {
            "editor_id": output.get("selectedEditorOrcId", ""),
            "editor_person_id": output.get("selectedEditorPersonId", ""),
            "assignment_result": assignment_result,
            "reasoning": output.get("reasoning", ""),
            "filtered_out_editors": output.get("filteredOutEditors", ""),
            "runner_up": output.get("runnerUp", "")
        }

    async def _call_assign_api(self, manuscript_submission, editor_id, state):
        """Make the API call to assign the editor."""
        if not self._assign_url:
            raise RuntimeError("Please provide ASSIGN_URL environment variable")

        self.logger.info(f"Assigning editor with API call to {self._assign_url}")

        async with aiohttp.ClientSession() as session:
            form_data = aiohttp.FormData()
            form_data.add_field('manuscript_id', manuscript_submission.manuscript_number)
            form_data.add_field('journal_id', manuscript_submission.journal_id)
            form_data.add_field('editor_id', editor_id)

            async with session.post(self._assign_url, data=form_data) as resp:
                try:
                    resp.raise_for_status()
                    api_response = await resp.text()
                    self.logger.info(f"Assign API response: {api_response}")
                except aiohttp.ClientResponseError as e:
                    response_body = await resp.text()
                    e.response_text = EditorAssignmentWorkflow.add_llm_response_to_body(response_body, state)
                    raise

        self.logger.info(
            f"Successfully assigned editor: Editor with ID {editor_id} assigned to manuscript {manuscript_submission.manuscript_number}")


    def _build_graph(self):
        graph = StateGraph(State)

        # Add all nodes
        graph.add_node("check_resubmission_status", self._check_resubmission_status)
        graph.add_node("validate_existing_assignment", self._validate_existing_assignment)
        graph.add_node("fetch_manuscript_data", self._fetch_manuscript_data)
        graph.add_node("generate_editor_recommendation", self._generate_editor_recommendation)
        graph.add_node("verify_recommendation", self._verify_recommendation)
        graph.add_node("execute_assignment", self._execute_assignment)
        graph.add_node("skip_assignment", self._skip_assignment)
        graph.add_node("use_existing_assignment", self._use_existing_assignment)

        # Start with resubmission check
        graph.add_edge(START, "check_resubmission_status")

        # Route after resubmission check
        graph.add_conditional_edges(
            "check_resubmission_status",
            self._route_after_resubmission_check,
            {
                "resubmission_flow": "validate_existing_assignment",
                "normal_flow": "fetch_manuscript_data"
            }
        )

        # Route after validation
        graph.add_conditional_edges(
            "validate_existing_assignment",
            self._route_after_assignment_validation,
            {
                "valid_assignment": "use_existing_assignment",
                "invalid_assignment": "fetch_manuscript_data"
            }
        )

        # Normal assignment flow
        graph.add_edge("fetch_manuscript_data", "generate_editor_recommendation")
        graph.add_edge("generate_editor_recommendation", "verify_recommendation")
        graph.add_conditional_edges(
            "verify_recommendation",
            self._should_assign_editor,
            {
                "assign": "execute_assignment",
                "skip": "skip_assignment"
            }
        )

        # All terminal nodes go to END
        graph.add_edge("execute_assignment", END)
        graph.add_edge("skip_assignment", END)
        graph.add_edge("use_existing_assignment", END)

        # Compile with optional session memory (checkpointer) and long-term memory (store)
        compile_kwargs = {}
        if self._checkpointer:
            compile_kwargs["checkpointer"] = self._checkpointer
        if self._store:
            compile_kwargs["store"] = self._store

        return graph.compile(**compile_kwargs)

    async def _run(self, manuscript_submission):
        initial_state = {"manuscript_submission": manuscript_submission}
        return self._graph.ainvoke(initial_state)

        
    async def _astream(self, manuscript_submission, config=None):
        initial_state = {"manuscript_submission": manuscript_submission}
        async for item in self._graph.astream(initial_state, config=config):
            yield item

    async def async_execute_workflow(self, manuscript_submission):
        # Build config with thread_id for session memory (checkpointing)
        config = None
        if self._checkpointer:
            thread_id = f"{manuscript_submission.journal_id}-{manuscript_submission.manuscript_number}"
            config = {"configurable": {"thread_id": thread_id}}
            self.logger.info("Session Memory: using thread_id=%s", thread_id)

        final_state = None
        async for step in self._astream(manuscript_submission, config=config):
            logging.info(step)
            final_state = step

        return final_state

    async def _save_to_long_term_memory(self, manuscript_submission, llm_response: dict):
        """Save editor assignment to long-term memory.
        
        Called inside graph nodes (before any external API calls) so the
        assignment decision is persisted even if the downstream call fails.
        """
        if not self._store:
            return
        try:
            memory_state = {
                "manuscript_submission": manuscript_submission,
                "editor_id": llm_response.get("selectedEditorOrcId", ""),
                "editor_person_id": llm_response.get("selectedEditorPersonId", ""),
                "reasoning": llm_response.get("reasoning", ""),
                "runner_up": llm_response.get("runnerUp", ""),
                "filtered_out_editors": llm_response.get("filteredOutEditors", ""),
            }
            self.logger.info("Long-term Memory: saving assignment for %s", manuscript_submission.manuscript_number)
            await save_assignment_to_memory(self._store, memory_state)
        except Exception as e:
            self.logger.warning("Long-term Memory save failed (continuing): %s", e)

    @staticmethod
    def _resolve_final_state(stream_output: dict, manuscript_submission=None) -> Optional[dict]:
        """Extract the state dict from the last stream output.
        
        Stream output is {node_name: node_output}. The terminal node output
        contains editor_person_id but not manuscript_submission, so we inject
        it from the original request.
        """
        for node_name, node_output in stream_output.items():
            if isinstance(node_output, dict) and "editor_person_id" in node_output:
                resolved = dict(node_output)
                if manuscript_submission and "manuscript_submission" not in resolved:
                    resolved["manuscript_submission"] = manuscript_submission
                return resolved
        return None

    @staticmethod
    def _make_llm_response_from_state(state):
        llm_response = EditorAssignmentWorkflow._extract_editor_assignment_output(state['editor_assignment_result'])
        return EditorAssignmentWorkflow._make_assignment_response(llm_response, "Assignment Failed")

    @staticmethod
    def add_llm_response_to_body(body, state):
        response = json.loads(body)
        response["llm_response"] = EditorAssignmentWorkflow._make_llm_response_from_state(state)
        return json.dumps(response)
