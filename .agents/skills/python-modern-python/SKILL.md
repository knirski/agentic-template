---
name: python-modern-python
description: Modern Python 3.12-3.14 language features and typing. Use for type parameters, type aliases, protocols, dataclasses, structural pattern matching, asyncio concurrency, cancellation, or selecting syntax for the suite's supported Python versions. For Temporal workflow asyncio rules, use python-temporal.
user-invocable: false
---

# Modern Python Features

Modern Python 3.12+ language features, type hints, and patterns.

## Type Hints

### Basic Types

```python
def greet(name: str) -> str:
    return f"Hello {name}"

age: int = 25
prices: list[float] = [9.99, 19.99]
mapping: dict[str, int] = {"a": 1}
```

### Unions and aliases

```python
# Modern syntax
def process(value: int | str) -> bool:
    ...

# Optional
def get_user(user_id: int) -> "User | None":
    ...

# Multiple types
type Result = int | str | bool
```

### Generic Types

```python
class Repository[T]:
    def get(self, id: int) -> T | None:
        raise NotImplementedError

    def save(self, entity: T) -> T:
        raise NotImplementedError

```

### Protocol (Structural Typing)

```python
from typing import Protocol

class Drawable(Protocol):
    """Structural type - any class with draw()"""
    def draw(self) -> None:
        ...

def render(obj: Drawable) -> None:
    """Works with any object that has draw()"""
    obj.draw()
```

## Pattern Matching

### Basic Matching

```python
def handle_command(command: str) -> str:
    match command:
        case "start":
            return "started"
        case "stop":
            return "stopped"
        case "status":
            return "status"
        case _:
            raise ValueError("Unknown command")
```

### Matching with Values

```python
def handle_http_status(status: int) -> str:
    match status:
        case 200:
            return "OK"
        case 404:
            return "Not Found"
        case 500 | 502 | 503:
            return "Server Error"
        case _:
            return "Unknown"
```

### Structural Pattern Matching

```python
def process_point(point: object) -> str:
    match point:
        case (0, 0):
            return "Origin"
        case (x, 0):
            return f"On X-axis at {x}"
        case (0, y):
            return f"On Y-axis at {y}"
        case (x, y):
            return f"At ({x}, {y})"
```

## Async/Await

### Async Functions

```python
import asyncio
from typing import Any

import httpx

async def fetch_data(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

async def main() -> None:
    data = await fetch_data("https://api.example.com")
    print(data)

asyncio.run(main())
```

### Concurrent Execution

```python
import asyncio

async def process_all(urls: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(fetch_data(url)) for url in urls]
    for task in tasks:
        results.append(task.result())
    return results
```

### Async Context Managers

```python
class AsyncDatabase:
    async def __aenter__(self) -> "AsyncDatabase":
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.disconnect()

async def read_database() -> None:
    async with AsyncDatabase() as db:
        await db.query()
```

## Dataclasses

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def distance_from_origin(self) -> float:
        return (self.x ** 2 + self.y ** 2) ** 0.5
```

## Walrus Operator

```python
# Assign and use in one expression
if (n := len(items)) > 10:
    print(f"Too many items: {n}")

# In comprehensions
results = [y for x in items if (y := process(x)) is not None]
```

## Modern String Formatting

```python
name = "Alice"
age = 30

# f-strings
message = f"Hello {name}, you are {age} years old"

# f-strings with expressions
message = f"In 5 years you'll be {age + 5}"

# Debug f-strings (Python 3.8+)
print(f"{name=}")  # name='Alice'
```

## References

- [Typing](references/typing.md): protocols, decorators, and static/runtime boundaries.
- [Async](references/async.md): TaskGroup, cancellation, and async iteration.
- [Pattern matching](references/pattern-matching.md): captures, guards, and exhaustiveness.
