# Testing Temporal Workflows

Use the [Temporal testing guide](https://docs.temporal.io/develop/python/best-practices/testing-suite) for current behavior.

```python
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

@activity.defn(name="my_activity")
async def replacement_activity(name: str) -> str:
    return "MOCKED"

async def test_workflow() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-queue",
            workflows=[MyWorkflow],
            activities=[replacement_activity],
        ):
            result = await env.client.execute_workflow(
                MyWorkflow.run,
                "World",
                id="test-workflow",
                task_queue="test-queue",
            )
    assert result == "Hello MOCKED"
```

Replacement activities must be decorated, use the real Activity's registered name, and accept compatible inputs. Do not register a plain `Mock` with a Worker.

Time skipping is global to an environment, primarily advances while awaiting workflow results, and does not skip while Activities run. Use a separate environment per concurrent test and unique workflow IDs/task queues. Use `ActivityEnvironment` for heartbeat and cancellation behavior. Use `Replayer` against saved histories in CI to catch nondeterminism after workflow changes.
