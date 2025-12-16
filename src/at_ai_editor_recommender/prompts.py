

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

### Assignment Steps

### STEP 1: ELIGIBILITY CHECK

**Remove editors whose institution matches ANY author institution:**

**MATCHES (COI):**
- Known abbreviations: MIT is same as Massachusetts Institute of Technology
- Same university, any campus: UC Berkeley is same as University of California, Berkeley
- Minor spelling variations of SAME institution

**NOT MATCHES (NO COI):**
- Parent/child orgs: Harvard Medical School is not same as  Harvard University
- Similar names: Global Research Lab is not same as Global Research Laboratory
- Affiliations: Google DeepMind is not same as Google/Alphabet

**Process:**
1. Compare each editor institution vs ALL author institutions
2. >90% confidence required for COI
3. Remove ONLY editors with confirmed COI
4. When uncertain: NO COI

**Proceed to Step 2 with all non-COI editors.**


### Step 2: Determine Which Assignment Path to Follow
**CRITICAL: EXACTLY ONE PATH MUST ALWAYS BE USED**

## PATH A: Journal-Specific Rules
{journal_specific_rules}

## PATH B: Global Rules for Non-Peer-Reviewed Administrative Manuscripts
**Use PATH B ONLY if BOTH of these are true:**
- Is Manuscript Peer-Reviewed = "No"
- Manuscript Type is EXACTLY one of:
  - Additions and Corrections, Announcement, Correspondence/Rebuttal, Center Stage, Editorial, Expression of Concern, First Reactions, The Hub, Retraction, Viewpoint

**If both apply, assign as follows:**

1. Assign to the Deputy Editor, if any Deputy Editor exists.
2. If no Deputy Editor, assign to the Editor-in-Chief, if any Editor-in-Chief exists.
3. If neither exists, leave selectedEditor empty.
4. Do not assign to an Editor-in-Chief if any Deputy Editors exists.

**Notes:**
- Only apply PATH B to the manuscript types listed above AND when Peer-Reviewed = "No".
- When multiple editors for a role, always pick the one with the lowest rank(1 beats 2, 2 beats 3, etc.).
- In path B assignment can only be to Deputy Editor or Editor-in-Chief.
- STOP once assignment is made—do not check any further paths or rules.
**If PATH B applies, but no eligible editor is available, do not make an assignment**
**If PATH B does NOT apply, you MUST use PATH C. Do not skip assignment.**

## PATH C: Standard Assignment (**MANDATORY IF A AND B DO NOT APPLY**)
**PATH C AUTOMATICALLY APPLIES TO EVERYTHING NOT HANDLED BY A OR B**

** PATH C RULE: MUST SELECT EDITOR WITH LOWEST RANK NUMBER **
** EDITORS WITH RANK NA ARE NOT ELIGIBLE FOR PATH C**

**ALGORITHM:**
**PATH C IGNORES EVERYTHING EXCEPT RANK:**
- Editor role : IRRELEVANT
- Manuscript type : IRRELEVANT
- Peer-review status : IRRELEVANT
- **ONLY RANK MATTERS: 1 is best, 2 is second best, etc.**

**EXAMPLES:**
- [Rank 3, Rank 1, Rank 5] : SELECT RANK 1
- [EIC rank 4, Executive rank 2] : SELECT RANK 2
- No editors : Leave empty

** VIOLATIONS:**
1. Not selecting an editor when editors exist
2. Selecting higher rank when lower exists
3. Considering anything besides rank
4. Considering editors with rank NA

** MANDATORY: If PATH C applies and editors exist, MUST assign to lowest rank **


Before returning your JSON:
- The selectedEditorOrcId and selectedEditorPersonId MUST match the actual editor you chose in your reasoning (role and rank).
- Do NOT use the ID of a different editor.
- Double-check for consistency before output.

## Output Format
**CRITICAL: Return ONLY valid JSON - no additional text, explanations, or formatting**
Return only a JSON object with the following fields and no other text or explanations:
{{
  "selectedEditorOrcId": "editor's ORCID or empty-string",
  "selectedEditorPersonId": "editor's personId or empty-string",
  "reasoning": "Brief 2-3 sentence explanation of decision",
  "runnerUp": "Note on runner-up if applicable (e.g., 'Editor X with reasoning')",
  "filteredOutEditors": "List of filtered editor IDs with reasons (e.g., 'Editor A: Reason, Editor B: Reason')"
}}

### Input Data:

## Manuscript Information
{manuscript_information}

## Available Editors
{available_editors}
"""