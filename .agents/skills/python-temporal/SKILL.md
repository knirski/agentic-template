---
name: python-temporal
description: Temporal Python SDK (temporalio) workflows, activities, workers, Signals, Queries, Updates, retries, timeouts, heartbeats, cancellation, determinism, testing, replay, versioning, and payload handling. Use for Temporal-specific orchestration or nondeterminism and sandbox errors.
user-invocable: false
---

# Temporal Workflow Orchestration

Temporal SDK patterns for durable workflows. Workflows replay, so determinism is the primary correctness constraint.

## Determinism First

Workflow code must not perform network, database, filesystem, subprocess, or blocking external work. Put those effects in Activities. Use `workflow.now()`, `workflow.random()`, and `workflow.uuid4()` rather than ambient nondeterministic APIs. Workflows are sandboxed by default; keep workflow modules side-effect free and pass known activity/model imports through `workflow.unsafe.imports_passed_through()`.

## Worker Setup

```python
from temporalio.client import Client
from temporalio.worker import Worker

async def main() -> None:
    client = await Client.connect("localhost:7233")

    async with Worker(
        client,
        task_queue="my-task-queue",
        workflows=[MyWorkflow],
        activities=[my_activity],
    ):
        await stop_event.wait()
```

## Workflow Definition

```python
from datetime import timedelta

from temporalio import workflow

@workflow.defn
class MyWorkflow:
    @workflow.run
    async def run(self, name: str) -> str:
        """Workflow run method"""
        result = await workflow.execute_activity(
            my_activity,
            name,
            start_to_close_timeout=timedelta(seconds=30),
        )

        return f"Hello {result}"
```

## Activity Implementation

```python
from temporalio import activity

@activity.defn
async def my_activity(name: str) -> str:
    """Activities are at-least-once and must be idempotent."""
    return name.upper()
```

## Starting Workflows

```python
from temporalio.client import Client

async def start_workflow():
    client = await Client.connect("localhost:7233")

    handle = await client.start_workflow(
        MyWorkflow.run,
        "World",
        id="my-workflow-id",
        task_queue="my-task-queue",
    )

    result = await handle.result()
    print(result)
```

## Error Handling

```python
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

@workflow.defn
class MyWorkflow:
    @workflow.run
    async def run(self) -> str:
        try:
            result = await workflow.execute_activity(
                risky_activity,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except ActivityError:
            raise

        return result
```

`start_to_close_timeout` is per attempt. Use `schedule_to_close_timeout` when total elapsed work, including retries, must be bounded. Long-running Activities should heartbeat progress and honor cancellation. Do not share an `AsyncSession` or other mutable client across concurrent Activities without its own safety guarantees.

## Signals, Queries, and Updates

```python
@workflow.defn
class OrderWorkflow:
    def __init__(self) -> None:
        self.status = "pending"

    @workflow.run
    async def run(self, order_id: str) -> str:
        await workflow.wait_condition(lambda: self.status == "approved")
        return "Order processed"

    @workflow.signal
    def approve(self) -> None:
        """Signal to approve order"""
        self.status = "approved"

    @workflow.query
    def get_status(self) -> str:
        """Query current status"""
        return self.status

    @workflow.update
    def set_status(self, status: str) -> str:
        self.status = status
        return self.status
```

Queries are synchronous and read-only. Signals do not return results. Updates can validate, mutate state, and return a result. Coordinate async handlers and wait for `workflow.all_handlers_finished` before a workflow completes when handlers may still be running.

## Safe evolution

Open executions replay old history. Use `workflow.patched()` and then `workflow.deprecate_patch()` for replay-breaking changes, and run `Replayer` checks against representative histories before deployment. Use current Worker Deployment Versioning for rollout isolation; do not introduce legacy Build-ID routing APIs.

## References

- [Patterns](references/patterns.md): retries, compensations, fan-out, and approvals.
- [Testing](references/testing.md): time skipping, replacement Activities, replay, and activity tests.

Do not put secrets in Workflow IDs, task queues, Search Attributes, or payloads. Payloads and failure data are persisted; use a configured PayloadCodec and failure conversion policy when encryption or redaction is required.
