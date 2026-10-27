"""Worker throttles unchanged durable waits while authenticated wake changes remain useful."""

import asyncio

from aced import ApprovalStatus, Goal
from tests.test_runtime import compose


async def test_unchanged_due_wait_is_throttled_without_writes_and_new_wake_bypasses_it():
    runtime, clock, runner, infra, _ = compose()
    infra.approval = ApprovalStatus.WAITING
    view = await runtime.start(Goal("demo", "Learn"), key="worker-wait")
    waiting = await runtime.advance(view.id)
    clock.tick(runtime.projects["demo"].poll_seconds)
    stop = asyncio.Event()
    first, second = asyncio.Event(), asyncio.Event()
    checks = 0
    advance = runtime.advance

    async def observed(run_id):
        nonlocal checks
        result = await advance(run_id)
        checks += 1
        (first if checks == 1 else second).set()
        return result

    runtime.advance = observed
    worker = asyncio.create_task(runtime.run_worker(stop, interval=0.001))
    try:
        await asyncio.wait_for(first.wait(), timeout=1)
        # Many worker ticks pass; no approval read, model launch or persistence
        # is needed until the configured native-record polling period elapses.
        await asyncio.sleep(0.025)
        assert checks == 1 and not runner.starts
        assert (await runtime.inspect(view.id)).revision == waiting.revision
        await runtime.record_observation(view.id, "native:approval-request-updated")
        await asyncio.wait_for(second.wait(), timeout=1)
        assert checks == 2 and not runner.starts
        assert (await runtime.inspect(view.id)).revision == waiting.revision + 1
    finally:
        stop.set()
        await asyncio.wait_for(worker, timeout=1)
        await runtime.close()
