# Temporal Workflow Patterns

Read the [Temporal Python documentation](https://docs.temporal.io/develop/python) for current SDK contracts.

## Compensation

Activities can execute more than once, and an effect can have happened even if its completion was not recorded. Register each compensation before its side effect, make effects idempotent with stable operation keys, and compensate only completed steps in reverse order.

```python
import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

from temporalio import workflow

Activity = Callable[[str], Awaitable[None]]
OPTIONS = {"start_to_close_timeout": timedelta(seconds=30)}

@workflow.defn
class SagaWorkflow:
    @workflow.run
    async def run(self, order_id: str) -> None:
        compensations: list[Activity] = []
        try:
            compensations.append(release_inventory)
            await workflow.execute_activity(reserve_inventory, order_id, **OPTIONS)
            compensations.append(refund_payment)
            await workflow.execute_activity(charge_payment, order_id, **OPTIONS)
            compensations.append(cancel_shipment)
            await workflow.execute_activity(create_shipment, order_id, **OPTIONS)
        except asyncio.CancelledError:
            # Define cancellation policy explicitly; this example compensates then re-raises.
            for compensate in reversed(compensations):
                await workflow.execute_activity(compensate, order_id, **OPTIONS)
            raise
        except Exception:
            for compensate in reversed(compensations):
                await workflow.execute_activity(compensate, order_id, **OPTIONS)
            raise
```

Production systems must decide whether cancellation waits for, shields, or abandons compensation and must record enough state for idempotent recovery.

## Fan-out and approval

`asyncio.gather()` is supported by Temporal workflow code. Bound fan-out by Worker and downstream capacity.

```python
results = await asyncio.gather(
    *[
        workflow.execute_activity(
            process_item,
            item,
            start_to_close_timeout=timedelta(seconds=30),
        )
        for item in items
    ]
)
```

`workflow.wait_condition(..., timeout=...)` raises `asyncio.TimeoutError`; it does not return false. Catch the error and run a timeout-specific Activity with required timeout options.
