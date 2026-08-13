# Structural Pattern Matching

`match` uses patterns, not equality alone. A bare name captures a value; use a qualified name for constants. Sequence patterns match sequences, not just tuples, and exclude `str`, `bytes`, and `bytearray`. Mapping patterns ignore extra keys.

```python
def classify(point: object) -> str:
    match point:
        case (0, 0):
            return "origin"
        case (x, y) if x > y:
            return "x > y"
        case (x, y) if y > x:
            return "y > x"
        case (x, x):
            return "diagonal"
        case _:
            raise ValueError("expected a two-value point")
```

Guards run after bindings and can raise. A non-matching `match` does nothing, so include a catch-all whenever a non-match is an error. For tagged unions, combine exhaustive cases with `typing.assert_never()` where a type checker can verify the remaining branch.
