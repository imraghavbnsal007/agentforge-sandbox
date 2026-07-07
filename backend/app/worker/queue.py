from typing import Protocol

from arq.connections import ArqRedis


class JobQueue(Protocol):
    async def enqueue_run_agent(self, task_id: int) -> None: ...

    async def enqueue_publish_task(self, task_id: int) -> None: ...


class ArqJobQueue:
    def __init__(self, pool: ArqRedis) -> None:
        self.pool = pool

    async def enqueue_run_agent(self, task_id: int) -> None:
        await self.pool.enqueue_job("run_agent", task_id)

    async def enqueue_publish_task(self, task_id: int) -> None:
        await self.pool.enqueue_job("publish_task", task_id)
