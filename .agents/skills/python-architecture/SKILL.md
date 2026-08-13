---
name: python-architecture
description: "Python application architecture for complex business behavior: functional decisions and effects, ports and adapters, aggregates, transaction ownership, and bounded contexts. Use when choosing application or domain boundaries, modeling evolving invariants, or deciding whether DDD is warranted. Do not apply rich DDD layers automatically to simple CRUD or framework DTOs."
user-invocable: false
---

# Python Application Architecture

Use the smallest architecture that protects meaningful business invariants. A focused application function and persistence adapter often suffice for CRUD; use aggregates and richer domain modeling when business rules are complex and evolving.

## Core Principle: Functional Core / Imperative Shell

Separate pure business logic from side effects:

- **Functional Core**: Pure functions, business logic, no IO
- **Imperative Shell**: Coordinates external dependencies, handles side effects

See [references/functional-core.md](references/functional-core.md) for detailed patterns and examples.

## Layered Architecture

Source-code dependencies point inward:

```
HTTP adapter ─┐
              v
         Application use case → Domain
              ^
Database adapter implementing an application/domain port
```

Adapters depend on the application/domain. Domain objects never import FastAPI/Pydantic request models or ORM records.

**Responsibilities:**
- **Domain**: Business state, invariants, and decisions.
- **Application use case**: Coordinates ports, transactions, and effects.
- **Repository port**: Domain-oriented storage contract.
- **Adapters**: Translate HTTP/Pydantic and ORM/database representations.

## Domain Models

### Entity Example

```python
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

@dataclass
class Order:
    """Entity - has identity and encapsulated behavior"""
    id: UUID
    customer_id: UUID
    total: Decimal
    status: str = "pending"

    def apply_discount(self, rate: Decimal) -> None:
        """Business rule - encapsulated in entity"""
        if self.status != "pending" or not Decimal("0") <= rate <= Decimal("1"):
            raise ValueError("Invalid discount")
        self.total *= Decimal("1") - rate
```

### Value Object Example

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Money:
    """A shallowly immutable value object."""
    amount: Decimal
    currency: str

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(self.amount + other.amount, self.currency)
```

See [references/ddd.md](references/ddd.md) for aggregates, bounded contexts, and domain services.

## Repository Pattern

Abstract storage behind interface:

```python
from typing import Protocol

class OrderRepository(Protocol):
    def get(self, order_id: UUID) -> Order | None: ...
    def save(self, order: Order) -> None: ...

class PostgresOrderRepository(OrderRepository):
    """Concrete implementation"""

    def get(self, order_id: UUID) -> Order | None:
        record = self.session.get(OrderRecord, order_id)
        return record_to_order(record) if record else None

    def save(self, order: Order) -> None:
        self.session.add(order_to_record(order))
```

The use case owns `with session.begin():`, allowing multiple repository operations and an outbox write to commit atomically.

## Data Modeling

- **dataclasses**: Domain models and internal logic (lightweight, standard library)
- **Pydantic**: API boundaries (validation, JSON schema, OpenAPI)
- **Adapters/mappers**: API request to command, domain result to response, and ORM record to domain aggregate

See [references/data-modeling.md](references/data-modeling.md) for validation patterns, Pydantic features, and transformation examples.

## Best Practices

1. **Pure functions first** - Write business logic without IO dependencies
2. **Entity encapsulation** - Keep business rules inside entities
3. **Repository abstraction** - Use it when persistence isolation adds value
4. **Validate at every appropriate boundary** - Transport shape at APIs, invariant state in domain objects
5. **Immutable value objects** - Prefer immutable contained fields; `frozen=True` is shallow
6. **Single Responsibility** - Each layer has one reason to change
7. **Dependency direction** - Always depend on abstractions, not implementations

## Anti-Patterns

❌ **Anemic Domain Model** - Only when complex business behavior is spread across unrelated services
❌ **Transaction Script** - Only when it obscures complex evolving invariants; it is valid for simple CRUD
❌ **Leaky Abstraction** - Repository exposing database details
❌ **God Object** - Entity with too many responsibilities
❌ **Mixed Concerns** - Business logic calling IO directly

For detailed examples, patterns, and decision trees, see the reference materials:
- [references/functional-core.md](references/functional-core.md) - Core vs shell separation
- [references/ddd.md](references/ddd.md) - DDD patterns, aggregates, bounded contexts
- [references/data-modeling.md](references/data-modeling.md) - dataclasses, Pydantic, transformations