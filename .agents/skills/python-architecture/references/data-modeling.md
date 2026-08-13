# Boundary Models and Mapping

Use dataclasses or ordinary classes for domain state and Pydantic for HTTP/request boundaries. Pydantic models are coercive and ignore extra fields by default; choose `ConfigDict(strict=True, extra="forbid")` for boundaries where accidental coercion or ignored input is risky.

Mapping belongs to adapters:

```text
HTTP request DTO -> command/value objects -> domain aggregate
domain aggregate -> response DTO
ORM record <-> domain aggregate
```

This keeps domain code independent of FastAPI, Pydantic, and SQLAlchemy imports. Domain constructors and state transitions still enforce invariants because data also enters from jobs, messages, persistence, and tests.

Use `Annotated[..., Depends(...)]` for FastAPI service injection. Handle `session.get()` returning `None` before Pydantic `model_validate()`. `EmailStr` requires the `email-validator` dependency.