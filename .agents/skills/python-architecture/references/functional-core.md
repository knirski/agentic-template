# Functional Decisions and Effects

A functional core computes decisions from explicit inputs. An imperative shell performs I/O, persistence, logging, and retries. Local list mutation does not make a function impure; mutating inputs, globals, or external systems does.

```python
from dataclasses import dataclass
from decimal import Decimal

@dataclass(frozen=True)
class Decision:
    charge_amount: Decimal
    send_receipt: bool

def decide_checkout(total: Decimal, is_paid: bool) -> Decision:
    if total < 0:
        raise ValueError("total cannot be negative")
    return Decision(charge_amount=Decimal("0") if is_paid else total, send_receipt=True)
```

This makes the decision easy to unit test. It does not make execution retry-safe: charging, email, and persistence need durable state, provider idempotency keys, and often an outbox or workflow. Logging and caching are controlled effects, not pure operations.

Test the core densely and add focused integration tests for transaction boundaries, adapters, error mapping, and critical wiring. A thin shell needs fewer tests, not zero tests.