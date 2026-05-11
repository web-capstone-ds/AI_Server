import asyncio
import structlog
from typing import Set

logger = structlog.get_logger()

class JobTracker:
    def __init__(self):
        self.active_jobs: Set[str] = set()
        self._all_jobs_done = asyncio.Event()
        self._all_jobs_done.set()

    def add_job(self, batch_id: str):
        self.active_jobs.add(batch_id)
        self._all_jobs_done.clear()
        logger.debug("job_tracked", batch_id=batch_id, active_count=len(self.active_jobs))

    def remove_job(self, batch_id: str):
        if batch_id in self.active_jobs:
            self.active_jobs.remove(batch_id)
        if not self.active_jobs:
            self._all_jobs_done.set()
        logger.debug("job_untracked", batch_id=batch_id, active_count=len(self.active_jobs))

    async def wait_for_completion(self, timeout: float = 30.0):
        if not self.active_jobs:
            return
        
        logger.info("waiting_for_jobs_completion", count=len(self.active_jobs))
        try:
            await asyncio.wait_for(self._all_jobs_done.wait(), timeout=timeout)
            logger.info("all_jobs_completed")
        except asyncio.TimeoutError:
            logger.warning("shutdown_timeout_reached", active_jobs=list(self.active_jobs))

job_tracker = JobTracker()
