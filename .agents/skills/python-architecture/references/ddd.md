# DDD When It Helps

Use DDD concepts for complex, evolving business invariants. Simple CRUD, reporting, and integration services often need only focused application functions and persistence adapters.

Prefer immutable value objects with immutable members. `@dataclass(frozen=True)` is a shallow attribute-assignment guard, not deep immutability. Money needs an explicit currency, finite-value, rounding, and signed-versus-nonnegative policy; retain `Decimal` rather than converting it to float.

An aggregate root is the update entry point for a consistency boundary. Keep mutable state private, expose read-only views, and enforce lifecycle rules in every mutation method. ID-only cross-aggregate references and one-aggregate transactions are useful defaults, not laws: use a shared ACID transaction when an invariant truly requires it, then reconsider the aggregate boundary if this is frequent.

Repositories are domain-oriented ports. Concrete adapters map ORM records and manage no per-method commits. A use case owns the transaction and atomically captures outbox events when external publication matters. Domain events should contain an injected or passed aware UTC timestamp, use immutable records, and have an explicit capture and delivery lifecycle.