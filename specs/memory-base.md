# AJ-24 — Memory abstract base class + 5 chat-history backends

> Tracked in [`board.json`](../board.json) as `AJ-24`. AJ-1 stubbed a `Memory`
> ABC + a placeholder `InMemoryMemory` for the escape hatch path.
> AJ-24 ships the real contract + five concrete backends + URL
> resolution.
>
> **Scope is chat-history only**. Semantic memory / RAG (Qdrant,
> pgvector) lives in AJ-62 (separate item).

## What

1. **`Memory` ABC** with `get(session_id) -> list[Message]`,
   `append(session_id, message) -> None`, `clear(session_id) -> None`.
   All async.
2. **`InMemoryMemory`** — `dict[str, list[Message]]` per-process.
   Default when `memory=None`. Polishes the AJ-1 stub.
3. **`RedisMemory`** — Redis-backed via `redis.asyncio`. Behind
   `ajolopy[redis]` extra. URL: `redis://host:port/db`.
4. **`PostgresMemory`** — PostgreSQL-backed via `asyncpg`. Behind
   `ajolopy[postgres]` extra. URL: `postgresql://user:pass@host/db`.
5. **`MongoDBMemory`** — MongoDB-backed via `motor` (async wrapper
   around `pymongo`). Behind `ajolopy[mongo]` extra. URL:
   `mongodb://host/db`.
6. **`SQLiteMemory`** — SQLite-backed via stdlib `sqlite3` +
   `asyncio.to_thread`. No extra needed (stdlib). URL:
   `sqlite:///path/to/file.db`.
7. **`resolve_memory(spec) -> Memory | None`** — dispatches on URL
   scheme.

## Why

Brief v4.0 §`@Agent` shows `@Agent(memory="redis://...")` as the
killer-demo example. The five concrete backends cover the most
popular chat-history persistence choices: Redis (fast ephemeral),
Postgres / MongoDB (durable enterprise), SQLite (zero-config local),
InMemory (testing). Vector-store integration for RAG is a separate
abstraction tracked in AJ-62.

## Public surface (v0.1)

```python
from ajolopy import Agent
from ajolopy.memory import (
    Memory, InMemoryMemory, RedisMemory, PostgresMemory,
    MongoDBMemory, SQLiteMemory,
)

# URL forms (default routing):
@Agent(memory="redis://localhost:6379/0")          # RedisMemory
@Agent(memory="postgresql://user:pass@host/db")    # PostgresMemory
@Agent(memory="mongodb://localhost:27017/myapp")   # MongoDBMemory
@Agent(memory="sqlite:///./memory.db")             # SQLiteMemory
@Agent(memory="memory://")                         # InMemoryMemory (explicit)
@Agent(memory=None)                                # InMemoryMemory (default)

# Instance form (escape hatch / config):
@Agent(memory=RedisMemory("redis://...", prefix="myapp:mem:"))

# Custom subclass:
class NotionMemory(Memory):
    async def get(self, session_id): ...
    async def append(self, session_id, message): ...
    async def clear(self, session_id): ...
```

### `Memory` ABC

```python
class Memory(abc.ABC):
    @abc.abstractmethod
    async def get(self, session_id: str) -> list[Message]: ...

    @abc.abstractmethod
    async def append(self, session_id: str, message: Message) -> None: ...

    @abc.abstractmethod
    async def clear(self, session_id: str) -> None: ...
```

### `InMemoryMemory`

```python
class InMemoryMemory(Memory):
    def __init__(self) -> None: ...
```

Per-instance `dict[str, list[Message]]`. Per-instance isolation. Not
shared across processes.

### `RedisMemory`

```python
class RedisMemory(Memory):
    def __init__(self, url: str, *, prefix: str = "ajolopy:memory:") -> None: ...
```

Lazy-imports `redis.asyncio` at construction (`MemoryDependencyError`
on missing extra). Each session = one Redis LIST keyed
`<prefix><session_id>`. Messages JSON-serialised via
`Message.model_dump_json()`. `RPUSH` for append, `LRANGE 0 -1` for
get, `DEL` for clear.

### `PostgresMemory`

```python
class PostgresMemory(Memory):
    def __init__(
        self,
        url: str,
        *,
        table: str = "ajolopy_memory",
    ) -> None: ...
```

Lazy-imports `asyncpg`. Schema (created idempotently at first use):

```sql
CREATE TABLE IF NOT EXISTS <table> (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    message_json JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_<table>_session ON <table>(session_id, id);
```

Uses a connection pool (`asyncpg.create_pool(url)`). `append` does
`INSERT`. `get` does `SELECT ... ORDER BY id`. `clear` does
`DELETE WHERE session_id = $1`.

### `MongoDBMemory`

```python
class MongoDBMemory(Memory):
    def __init__(
        self,
        url: str,
        *,
        collection: str = "ajolopy_memory",
    ) -> None: ...
```

Lazy-imports `motor.motor_asyncio`. Database is derived from the URL
path component (`mongodb://host/<db>`). Documents store one message
each with `{session_id, message_json, created_at}` shape. Index on
`(session_id, created_at)` created on first use.

### `SQLiteMemory`

```python
class SQLiteMemory(Memory):
    def __init__(self, path: str) -> None: ...
```

Stdlib `sqlite3` wrapped in `asyncio.to_thread`. Same schema as
Postgres but `TEXT` instead of `JSONB`. `path` accepts `:memory:` for
ephemeral test databases. Parent dir created if missing.

### `resolve_memory(spec) -> Memory | None`

```python
def resolve_memory(spec: object) -> Memory | None: ...
```

| Form                              | Resolution                              |
|-----------------------------------|-----------------------------------------|
| `None`                            | `None` (no memory)                      |
| `Memory` instance                 | The instance verbatim                   |
| `"redis://..."`                   | `RedisMemory(url=spec)`                 |
| `"postgresql://..."` / `"postgres://..."` | `PostgresMemory(url=spec)`      |
| `"mongodb://..."`                 | `MongoDBMemory(url=spec)`               |
| `"sqlite:///..."` / `":memory:"`  | `SQLiteMemory(path=...)`                |
| `"memory://"`                     | `InMemoryMemory()`                      |
| Anything else                     | `MemoryConfigError`                     |

### Errors

```python
class MemoryError(Exception): ...
class MemoryConfigError(MemoryError): ...
class MemoryDependencyError(MemoryError): ...
class MemoryRuntimeError(MemoryError): ...
```

## Cross-cuts

### AJ-1 — replacement
- `src/ajolopy/memory.py` currently has the stub. AJ-24 promotes it
  to a sub-package `src/ajolopy/memory/`. `AgentRuntime`'s call sites
  (`self._memory.get/append`) are unchanged.

### pyproject — additive
- `[project.optional-dependencies]`:
  - `redis = ["redis>=5.0"]`
  - `postgres = ["asyncpg>=0.30"]`
  - `mongo = ["motor>=3.6"]`
- SQLite needs NO extra (stdlib).
- Convenience meta-extra: `memory-all = ["redis>=5.0", "asyncpg>=0.30", "motor>=3.6"]`.

## Out of scope

- **Semantic memory / vector stores** → AJ-62 (separate item).
- **Multi-session aggregation** (querying across sessions, summaries
  across users) → v0.2.
- **Schema migrations** for Postgres/Mongo — v0.1 creates the schema
  idempotently on first use; full migration tooling is post-v0.1.
- **Connection-pool tuning** kwargs (max_size, etc.) — v0.1 uses
  library defaults.

## Acceptance criteria

### `Memory` ABC
- [ ] Cannot instantiate directly.
- [ ] Subclass implementing only `get` still abstract.

### `InMemoryMemory`
- [ ] Fresh: `get("s1") -> []`.
- [ ] `append` then `get` returns the message.
- [ ] Sessions isolated.
- [ ] `clear` empties just that session.
- [ ] Two instances are independent.

### `RedisMemory`
- [ ] Round-trip semantics (verified against `fakeredis.aioredis` or
      similar fake).
- [ ] Missing `ajolopy[redis]` extra → `MemoryDependencyError` at
      construction.
- [ ] `prefix` kwarg namespaces keys.
- [ ] `clear` deletes the LIST key.

### `PostgresMemory`
- [ ] Round-trip semantics (verified against a `pytest-asyncpg`-style
      fixture using a real Postgres in a container OR a minimal
      `FakePostgres` test double — pick the cheaper one).
- [ ] Missing `ajolopy[postgres]` extra → `MemoryDependencyError`.
- [ ] Schema created idempotently on first append (re-call no-op).
- [ ] `table` kwarg redirects to a different table name.

### `MongoDBMemory`
- [ ] Round-trip semantics (use `mongomock-motor` or a real-Mongo
      container — pick the cheaper one).
- [ ] Missing `ajolopy[mongo]` extra → `MemoryDependencyError`.
- [ ] Collection name from kwarg.

### `SQLiteMemory`
- [ ] Round-trip with `:memory:` path.
- [ ] File path creates parent dir.
- [ ] Schema idempotent.

### `resolve_memory`
- [ ] All 7 URL schemes resolve to the right class.
- [ ] Instances pass through.
- [ ] Bad scheme → `MemoryConfigError`.
- [ ] `sqlite:///path` extracts the path correctly.
- [ ] `:memory:` short-form → `SQLiteMemory(":memory:")`.

### Public re-exports
- [ ] `from ajolopy.memory import (Memory, InMemoryMemory,
      RedisMemory, PostgresMemory, MongoDBMemory, SQLiteMemory,
      resolve_memory, MemoryError, MemoryConfigError,
      MemoryDependencyError, MemoryRuntimeError)` works.
- [ ] No top-level re-exports.

### Integration with `@Agent`
- [ ] `@Agent(memory="memory://")` → `InMemoryMemory` attached.
- [ ] `await agent.run("hi")` then a second call sees the first
      turn in history.
- [ ] Shared `InMemoryMemory()` instance lets two agents share
      history.

## Implementation pointers

- `src/ajolopy/memory/` — convert from single file to sub-package:
  - `__init__.py` — public re-exports.
  - `base.py` — `Memory` ABC.
  - `errors.py` — error hierarchy.
  - `in_memory.py` — `InMemoryMemory`.
  - `redis_memory.py` — `RedisMemory` (lazy `redis.asyncio`).
  - `postgres_memory.py` — `PostgresMemory` (lazy `asyncpg`).
  - `mongo_memory.py` — `MongoDBMemory` (lazy `motor`).
  - `sqlite_memory.py` — `SQLiteMemory` (stdlib + to_thread).
  - `resolver.py` — `resolve_memory(spec)`.
- `pyproject.toml`: add 3 new extras + 1 meta-extra.
- Tests: `tests/memory/`. One file per backend + resolver + public
  API + agent integration. Use lightweight fakes
  (`fakeredis`, `mongomock-motor`) where mature options exist; for
  Postgres, prefer a minimal in-test SQL fake or skip the network
  test with a clear marker.

## Implementation notes

(Empty — populated by the implementation PR.)
