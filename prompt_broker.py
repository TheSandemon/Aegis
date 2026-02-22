"""
Aegis Prompt Broker — Centralized Rate-Limited LLM Request Queue
Enforces strict 1-prompt-per-minute pacing across all agents.
"""

import asyncio
import time
import logging
from typing import Any, Callable, Coroutine
from dataclasses import dataclass, field

logger = logging.getLogger("aegis.broker")


@dataclass
class PromptRequest:
    """A single outbound LLM prompt request."""
    card_id: int
    agent_name: str
    prompt: str
    callback: Callable[..., Coroutine]  # async callback(response) when done
    retries: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)


class PromptBroker:
    """
    Centralized tollbooth for all outbound LLM requests.
    Enforces rate limiting to protect API quotas.
    """

    def __init__(self, prompts_per_minute: int = 1, max_retries: int = 3):
        self.queue: asyncio.Queue[PromptRequest] = asyncio.Queue()
        self.dead_letter: list[PromptRequest] = []
        self.prompts_per_minute = prompts_per_minute
        self.max_retries = max_retries
        self.interval = 60.0 / prompts_per_minute
        self.last_prompt_time: float = 0.0
        self._running = False
        self._task: asyncio.Task = None
        self._stats = {
            "total_submitted": 0,
            "total_processed": 0,
            "total_failed": 0,
            "total_retried": 0,
            "dead_letters": 0,
        }

    async def start(self):
        """Start the broker processing loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info(f"PromptBroker started: {self.prompts_per_minute} prompt(s)/min")

    async def stop(self):
        """Gracefully stop the broker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PromptBroker stopped")

    async def submit(self, request: PromptRequest):
        """Submit a prompt request to the queue."""
        self._stats["total_submitted"] += 1
        await self.queue.put(request)
        logger.info(
            f"Broker: Queued prompt for card {request.card_id} "
            f"(queue depth: {self.queue.qsize()})"
        )

    def get_stats(self) -> dict:
        """Returns broker statistics."""
        return {
            **self._stats,
            "queue_depth": self.queue.qsize(),
            "dead_letter_count": len(self.dead_letter),
        }

    async def _process_loop(self):
        """Main processing loop — enforces rate limiting."""
        while self._running:
            try:
                request = await asyncio.wait_for(self.queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # Enforce rate limit cooldown
            now = time.time()
            elapsed = now - self.last_prompt_time
            if elapsed < self.interval:
                wait_time = self.interval - elapsed
                logger.info(f"Broker: Rate limit — waiting {wait_time:.1f}s before next prompt")
                await asyncio.sleep(wait_time)

            # Execute the prompt
            try:
                self.last_prompt_time = time.time()
                await request.callback(request)
                self._stats["total_processed"] += 1
                logger.info(f"Broker: Processed prompt for card {request.card_id}")

            except Exception as e:
                logger.error(f"Broker: Prompt failed for card {request.card_id}: {e}")
                request.retries += 1

                if request.retries <= request.max_retries:
                    self._stats["total_retried"] += 1
                    logger.info(
                        f"Broker: Retrying card {request.card_id} "
                        f"(attempt {request.retries}/{request.max_retries})"
                    )
                    await self.queue.put(request)
                else:
                    self._stats["total_failed"] += 1
                    self._stats["dead_letters"] += 1
                    self.dead_letter.append(request)
                    logger.warning(
                        f"Broker: Dead-lettered prompt for card {request.card_id} "
                        f"after {request.max_retries} retries"
                    )

            self.queue.task_done()
