from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import TaskStatus
from app.core.exceptions import ConflictError, NotFoundError
from app.models import ProjectAnalysis, Task
from app.repositories.project_repo import ProjectRepository
from app.repositories.task_repo import TaskRepository
from app.schemas.task import TaskCreate
from app.services.github_config import is_github_project
from app.worker.queue import JobQueue


class TaskService:
    def __init__(self, session: AsyncSession, queue: JobQueue) -> None:
        self.session = session
        self.queue = queue
        self.tasks = TaskRepository(session)
        self.projects = ProjectRepository(session)

    async def create_task(self, data: TaskCreate) -> Task:
        project = await self.projects.get(data.project_id)
        if project is None:
            raise NotFoundError(f"Project {data.project_id} not found")
        task = Task(project_id=data.project_id, title=data.title, request=data.request)
        self.tasks.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        await self.queue.enqueue_run_agent(task.id)
        # First task on a never-analyzed GitHub project also kicks off analysis
        # (the explicit alternative to the Analyze button).
        if is_github_project(project):
            count = await self.session.scalar(
                select(func.count(ProjectAnalysis.id)).where(
                    ProjectAnalysis.project_id == project.id
                )
            )
            if count == 0:
                analysis = ProjectAnalysis(
                    project_id=project.id, file_summaries=[], suggestions=[]
                )
                self.session.add(analysis)
                await self.session.commit()
                await self.queue.enqueue_analyze_project(analysis.id)
        return task

    async def list_tasks(self, project_id: int | None = None) -> list[Task]:
        return await self.tasks.list(project_id)

    async def get_task_detail(self, task_id: int) -> Task:
        task = await self.tasks.get_with_runs(task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        return task

    async def retry_task(self, task_id: int) -> Task:
        """Re-enqueue an agent run for an existing task (a new AgentRun is created)."""
        task = await self.tasks.get(task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        task.status = TaskStatus.pending
        await self.session.commit()
        # updated_at is server-generated on UPDATE, so refresh before serializing.
        await self.session.refresh(task)
        await self.queue.enqueue_run_agent(task.id)
        return task

    async def approve_task(self, task_id: int) -> Task:
        """User approved the reviewed changes: publish them as a pull request."""
        task = await self._get_reviewable(task_id)
        task.status = TaskStatus.publishing
        await self.session.commit()
        await self.session.refresh(task)
        await self.queue.enqueue_publish_task(task.id)
        return task

    async def reject_task(self, task_id: int) -> Task:
        task = await self._get_reviewable(task_id)
        task.status = TaskStatus.rejected
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def _get_reviewable(self, task_id: int) -> Task:
        task = await self.tasks.get(task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        if task.status != TaskStatus.ready_for_review:
            raise ConflictError(
                f"Task {task_id} is {task.status}, not ready_for_review"
            )
        return task
