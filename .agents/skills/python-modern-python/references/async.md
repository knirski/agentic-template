# asyncio Patterns

Use `TaskGroup` for related concurrent work on Python 3.11+. It cancels sibling tasks when one fails and surfaces an exception group. Use `gather()` only when its result ordering and failure behavior are deliberate.

```python
import asyncio

async def fetch_all(urls: list[str]) -> list[str]:
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(fetch(url)) for url in urls]
    return [task.result() for task in tasks]
```

Propagate `asyncio.CancelledError` after cleanup. Do not catch broad exceptions around cancellation. Use timeouts, bounded concurrency, and an async client that is closed with `async with`. `asyncio.run()` is for the top-level entry point, never a thread already running an event loop.

`__aiter__` is synchronous and `__anext__` is async; raise `StopAsyncIteration` to finish an async iterator.
