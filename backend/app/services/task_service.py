from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import Task
from app.repositories.project_repo import ProjectRepository
from app.repositories.task_repo import TaskRepository
from app.schemas.task import TaskCreate
from app.worker.queue import JobQueue


class TaskService:
    def __init__(self, session: AsyncSession, queue: JobQueue) -> None:
        self.session = session
        self.queue = queue
        self.tasks = TaskRepository(session)
        self.projects = ProjectRepository(session)

    async def create_task(self, data: TaskCreate) -> Task:
        if await self.projects.get(data.project_id) is None:
            raise NotFoundError(f"Project {data.project_id} not found")
        task = Task(project_id=data.project_id, title=data.title, request=data.request)
        self.tasks.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        await self.queue.enqueue_run_agent(task.id)
        return task

    async def list_tasks(self, project_id: int | None = None) -> list[Task]:
        return await self.tasks.list(project_id)

    async def get_task_detail(self, task_id: int) -> Task:
        task = await self.tasks.get_with_runs(task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        return task
