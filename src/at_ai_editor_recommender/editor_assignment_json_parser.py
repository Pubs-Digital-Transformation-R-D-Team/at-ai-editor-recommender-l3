# filepath: /appl/jxv96/projects/at-ai-editor-recommender/src/at_ai_editor_recommender/editor_assignment_json_parser.py
import json
import re
import logging

class EditorAssignmentJsonParser:
    FIELDS = [
        "Selected Editor",
        "Reasoning",
        "Expertise Factor",
        "Workload Factor",
        "Runner up"
    ]

    @staticmethod
    def extract_json(text):
        """
        Extract JSON content from a Markdown code block or plain text.
        """
        match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            json_str = text.strip()
        return json_str

    @classmethod
    def parse(cls, text):
        """
        Parse the LLM output and return a dict with all expected fields (None if missing).
        """
        json_str = cls.extract_json(text)
        try:
            data = json.loads(json_str)
            logging.info("JSON parsed successfully.")
        except Exception as e:
            logging.error(f"Failed to parse JSON: {e}")
            raise
        return {
            "selectedEditorOrcId": data.get("selectedEditorOrcId"),
            "selectedEditorPersonId": data.get("selectedEditorPersonId"),
            "reasoning": data.get("reasoning"),
            "filteredOutEditors": data.get("filteredOutEditors"),
            # "expertiseFactor": data.get("expertiseFactor"),
            # "workloadFactor": data.get("workloadFactor") if "workloadFactor" in data else None,
            "runnerUp": data.get("runnerUp"),
        }