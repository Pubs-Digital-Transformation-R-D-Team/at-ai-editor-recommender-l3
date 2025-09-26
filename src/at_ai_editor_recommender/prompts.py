

# match with Shubham's prompt version
EDITOR_ASSIGNMENT_PROMPT_TEMPLATE_V2 = """
# Editor Assignment Protocol

## Important Instruction
Only consider the data provided in this prompt. Do not reference any external information or previous conversations.

## Assignment Rules (Priority Order)

## 1. Journal-Specific Rules (HIGHEST PRIORITY)
{journal_specific_rules}

## 2. Manuscript Type Global Routing
- Applies exclusively to non-peer-reviewed manuscripts (where Peer-Reviewed = "No")
- For special manuscript types that require editorial oversight:
  * Qualifying types: "Additions and Corrections", "Announcement", "Correspondence/Rebuttal",
    "Center Stage", "Editorial", "Expression of Concern", "First Reactions", "The Hub",
    "Retraction", or "Viewpoint"
  * Assignment priority order (only for qualifying types):
    1. First, assign to any available Deputy Editor (regardless of out-of-office status or workload-expertise rank)
    2. If no Deputy Editor exists, assign to any available Editor-in-Chief (regardless of out-of-office status or workload-expertise rank)
    3. If neither role is present in the editor list, do not assign (leave selectedEditor empty)

## 3. Pre-Assignment Filtering
For manuscripts not covered by rules 1-2:
- Filter out inactive editors (Active Status = No)
- Filter out editors based on contract dates:
  * Exclude editors whose contract has not started or just started (contract start date must be at least 1 day before September 09, 2025)
  * Exclude editors whose contract is about to expire (contract end date must be at least 5 days after September 09, 2025)
- Filter out editors who are unavailable due to out-of-office periods:
  * Exclude editors who have an out-of-office period that includes September 09, 2025
- Filter out editors who have institutional conflicts:
  * Exclude if any of the editor's institutions match any of the Author Institutions


## 4. Standard Assignment Logic
For remaining manuscripts after applying rules 1-3:
- If no editors remain, do not assign. leave selectedEditor empty ("").
- Select editor with the top workload-expertise rank (1 is the best, 2 is second best, and so on)
- The workload-expertise rank is a composite score that:
  * Balances editor expertise on the manuscript topic
  * Considers current workload distribution
  * Results in a single ranked list where lower numbers indicate more suitable candidates


## Output Format
Return only a JSON object with the following fields and no other text or explanations:
{{
  "selectedEditorOrcId": "editor's orcId or empty-string",
  "selectedEditorPersonId": "editor's personId or empty-string",
  "reasoning": "Brief 2-3 sentence explanation of decision",
  "runnerUp": "Note on runner-up if applicable (e.g., 'Editor X with 0.70 score')",
  "filteredOutEditors": "List of filtered editor IDs with reasons (e.g., 'Editor A: institutional conflict, Editor B: topic exclusion')"
}}

## Input data:

## Manuscript Information
{manuscript_information}


## Available Editors

{available_editors}
"""


EDITOR_ASSIGNMENT_PROMPT_TEMPLATE_V3 = """
# Editor Assignment Protocol

## Important Instruction
Only consider the data provided in this prompt. Do not reference any external information or previous conversations.

## Assignment Rules (Priority Order)

## 1. Journal-Specific Rules (HIGHEST PRIORITY)
{journal_specific_rules}


## 2. Manuscript Type Global Routing
- Applicable only if Peer-Reviewed is "No"
- For manuscript types "Additions and Corrections", "Announcement", "Correspondence/Rebuttal", "Center Stage", "Editorial", "Expression of Concern", "First Reactions", "The Hub", "Retraction", or "Viewpoint":
  * Assign to Deputy Editor if available
  * If no Deputy Editor, assign to Editor-in-Chief
  * This rule supersedes preferred editor selections

## 3. Pre-Assignment Filtering
For manuscripts not covered by rules 1-2:
- Filter out inactive editors (Active Status = No)
- Filter out editors whose contract start date is less than 1 day before 2025-09-09
- Filter out editors whose contract end date is less than 5 days after 2025-09-09
- Filter out editors who are out of office on 2025-09-09
- Filter out editors if any of their institution overlaps with Author Institutions
- Filter out editors in the Non-preferred Editor IDs list
- Filter out editors whose Topic Exclusions contain any Manuscript Topics

## 4. Standard Assignment Logic
For remaining manuscripts after applying rules 1-3:
- If no editors remain, do not assign. leave selectedEditor empty ("").
- If expertise score > 0.70: Weight expertise at 70%, workload at 30%
- If expertise score 0.50 to 0.70: Weight expertise at 60%, workload at 40%
- If a preferred editor is still in the pool, choose the one with the highest Expertise Score and least workload score.
- Else Select editor with the highest weighted score and lowest workload


## Output Format
Return only a JSON object with the following fields and no other text or explanations:
{{
  "selectedEditor": "editor-id-or-empty-string",
  "reasoning": "Brief 2-3 sentence explanation of decision",
  "expertiseFactor": "Brief note on expertise match (e.g., 'High match: 0.85 score')",
  "runnerUp": "Note on runner-up if applicable (e.g., 'Editor X with 0.70 score')",
  "filteredOutEditors": "List of filtered editor IDs with reasons (e.g., 'Editor A: institutional conflict, Editor B: topic exclusion')"
}}

## Input data:

## Manuscript Information
{manuscript_information}


## Available Editors

{available_editors}
"""

