# Python 3.12 Typing

Use built-in generics, union syntax, PEP 695 type parameters, and `type` aliases in new 3.12+ code.

```python
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, Protocol

type UserId = int
P = ParamSpec("P")

class Repository[T](Protocol):
    def get(self, identifier: UserId) -> T | None: ...

def logged[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return func(*args, **kwargs)
    return wrapper
```

Type annotations, `Protocol`, `TypedDict`, and `Literal` guide static checkers; Python does not enforce them at runtime. Add runtime validation where it is required. `typing.Callable` remains an alias but `collections.abc.Callable` is the current spelling.
