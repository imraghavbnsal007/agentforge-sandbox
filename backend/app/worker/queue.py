from typing import Protocol

from arq.connections import ArqRedis

from app.core.logging_config import current_context


class JobQueue(Protocol):
    async def enqueue_run_agent(self, task_id: int) -> None: ...

    async def enqueue_publish_task(self, task_id: int) -> None: ...

    async def enqueue_analyze_project(self, analysis_id: int) -> None: ...


class ArqJobQueue:
    def __init__(self, pool: ArqRedis) -> None:
        self.pool = pool

    def _request_id(self) -> str | None:
        """The enqueuing request's id, so a job's logs join up with it.

        Correlation only — never authorisation. The worker still re-reads
        everything it needs from the database.
        """
        return current_context().get("request_id")

    async def enqueue_run_agent(self, task_id: int) -> None:
        await self.pool.enqueue_job("run_agent", task_id, self._request_id())

    async def enqueue_publish_task(self, task_id: int) -> None:
        await self.pool.enqueue_job("publish_task", task_id, self._request_id())

    async def enqueue_analyze_project(self, analysis_id: int) -> None:
        await self.pool.enqueue_job(
            "analyze_project", analysis_id, self._request_id()
        )
