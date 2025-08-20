EDITOR_ASSIGNMENT_TASK = """
## Your Task
Select the most appropriate editor for this manuscript.

In your analysis:
1. First exclude any editors
    - editors who are not preferred
    - editors that are at maximum workload
    - editors with same institution as the author's institution for conflict of interest
2. For remaining editors, consider the following formula:
   - If expertise score > 0.7: Weight expertise at 70%, workload at 30%
   - If expertise score 0.5-0.7: Weight expertise at 60%, workload at 40%
3. Explain your reasoning for selecting this editor
4. If there are notable runner-up choices, briefly mention why they weren't selected

## Output Format
Selected Editor: [Editor ID]
Reasoning: [2-3 sentences explaining the decision]
Expertise Factor: [Brief note on expertise match]
Workload Factor: [Brief note on workload considerations]
"""

def get_editor_assignment_prompt(available_editors: str) -> str:
    return f"""
{available_editors}

{EDITOR_ASSIGNMENT_TASK}
"""

def get_verification_prompt(editor_assignment_prompt, editor_assignment_result):
    return f"""
Given the original editor assignment assignment task and the availability, please verify whether this assignment looks correct based
available data. If not correct, please provide reasoning:

## Original prompt

{editor_assignment_prompt}

## Editor assignment results

{editor_assignment_result}
"""
