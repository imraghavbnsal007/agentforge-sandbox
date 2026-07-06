"""Idempotent seed data so the dashboard has something to show.

Run inside the backend container: python -m app.seed
"""

import asyncio

from app.agent.mock_runner import MockRunner
from app.db.session import async_session_factory
from app.models import Project, Task
from app.repositories.project_repo import ProjectRepository
from app.services.run_service import RunService

PROJECT_NAME = "Sample Repo Service"


async def seed() -> None:
    async with async_session_factory() as session:
        repo = ProjectRepository(session)
        if await repo.get_by_name(PROJECT_NAME) is not None:
            print("Seed data already present, skipping.")
            return

        project = Project(
            name=PROJECT_NAME,
            description="Toy Python project the agent operates on in Phase 2.",
            repo_path="sample_repo",
        )
        session.add(project)
        await session.flush()

        completed = Task(
            project_id=project.id,
            title="Add multiply function to calculator",
            request="Add a multiply(a, b) function to the calculator module with tests.",
        )
        pending = Task(
            project_id=project.id,
            title="Add divide function with zero handling",
            request="Add divide(a, b) that raises a clear error when b is zero.",
        )
        session.add_all([completed, pending])
        await session.commit()

        # Run the real pipeline (mock runner, no delays) so the completed task
        # has a genuine AgentRun with real diffs and a real pytest result.
        await RunService(session, runner=MockRunner(delay=0)).execute_agent_run(
            completed.id
        )
        print(f"Seeded project {project.id} with tasks {completed.id}, {pending.id}.")


if __name__ == "__main__":
    asyncio.run(seed())
