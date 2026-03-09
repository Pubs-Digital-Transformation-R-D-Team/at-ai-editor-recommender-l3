from at_ai_editor_recommender.ee_agent_strands import EditorAssignmentAgent, ManuscriptSubmission
import logging
import asyncio

async def main():

    manuscript_submission = ManuscriptSubmission(
        manuscript_number="TEST_42",
        journal_id="JRN002",
        is_resubmit=False,
    )

    agent = EditorAssignmentAgent()
    await agent.async_execute_workflow(manuscript_submission)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    asyncio.run(main())