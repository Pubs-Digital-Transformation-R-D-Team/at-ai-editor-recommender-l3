# ---------------------------------------------------------------------------
# Fake data — no real EE-API or database needed for the POC
# ---------------------------------------------------------------------------

MANUSCRIPTS = {
    "MS-999": {
        "manuscript_number": "MS-999",
        "title": "Deep learning approaches for early detection of immunotherapy resistance in cancer patients",
        "authors": ["John Smith", "Jane Doe", "Robert Chen"],
        "abstract": (
            "This study investigates the application of deep neural networks to predict "
            "immunotherapy resistance in cancer patients using multi-omics data. "
            "We demonstrate 87% accuracy on a cohort of 2,400 patients."
        ),
        "topics": ["immunotherapy", "deep learning", "oncology", "cancer"],
        "journal": "CI",
    }
}

EDITORS = {
    "dr-jones": {
        "id": "0000-0001-1234-5678",
        "name": "Dr. Emily Jones",
        "person_id": "P001",
        "expertise": ["oncology", "immunotherapy", "clinical trials"],
        "current_load": 3,
        "max_load": 5,
    },
    "dr-lee": {
        "id": "0000-0002-2345-6789",
        "name": "Dr. Kevin Lee",
        "person_id": "P002",
        "expertise": ["immunology", "cancer biology", "molecular biology"],
        "current_load": 2,
        "max_load": 5,
    },
    "dr-smith": {
        "id": "0000-0003-3456-7890",
        "name": "Dr. Maria Smith",
        "person_id": "P003",
        "expertise": ["deep learning", "bioinformatics", "genomics"],
        "current_load": 1,
        "max_load": 5,
    },
}

# Publication history used by Strands COI agent to detect conflicts
EDITOR_HISTORY = {
    "Dr. Emily Jones": {
        "editor": "Dr. Emily Jones",
        "publications": [
            "Immunotherapy resistance mechanisms — co-authored with John Smith — Nature Medicine 2023",
            "CAR-T cell therapy advances — Cell 2022",
            "PD-1 checkpoint inhibitors — NEJM 2021",
        ],
        "coauthors": ["John Smith", "Dr. Peter Wang", "Dr. Lisa Chen"],
        "recent_manuscripts_handled": ["MS-100", "MS-200", "MS-300"],
    },
    "Dr. Kevin Lee": {
        "editor": "Dr. Kevin Lee",
        "publications": [
            "Tumor microenvironment and immunotherapy — Cancer Cell 2023",
            "Cytokine signaling in cancer — Nature Immunology 2022",
        ],
        "coauthors": ["Dr. Sarah Park", "Dr. James Wu"],
        "recent_manuscripts_handled": ["MS-400", "MS-500"],
    },
    "Dr. Maria Smith": {
        "editor": "Dr. Maria Smith",
        "publications": [
            "Graph neural networks for drug discovery — Nature Methods 2023",
            "Multi-omics data integration — Genome Biology 2022",
        ],
        "coauthors": ["Dr. Alex Brown", "Dr. Lisa White"],
        "recent_manuscripts_handled": ["MS-600", "MS-700"],
    },
}


def get_manuscript(manuscript_number: str) -> dict:
    ms = MANUSCRIPTS.get(manuscript_number)
    if not ms:
        raise ValueError(f"Manuscript {manuscript_number} not found")
    return ms


def get_editors_summary() -> str:
    lines = []
    for key, e in EDITORS.items():
        lines.append(
            f"- {e['name']} (ID: {e['id']}, PersonID: {e['person_id']}) | "
            f"Expertise: {', '.join(e['expertise'])} | "
            f"Current load: {e['current_load']}/{e['max_load']}"
        )
    return "\n".join(lines)


def get_editor_history(editor_name: str) -> dict:
    """Return publication/coauthor history for a given editor name."""
    # Try exact match first
    if editor_name in EDITOR_HISTORY:
        return EDITOR_HISTORY[editor_name]
    # Try case-insensitive partial match
    for name, history in EDITOR_HISTORY.items():
        if editor_name.lower() in name.lower() or name.lower() in editor_name.lower():
            return history
    return {
        "editor": editor_name,
        "publications": [],
        "coauthors": [],
        "recent_manuscripts_handled": [],
        "note": f"No history found for {editor_name}",
    }
