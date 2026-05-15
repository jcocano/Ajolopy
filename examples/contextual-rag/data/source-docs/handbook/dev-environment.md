# Developer environment

The Tlaltipac monorepo targets Python 3.14 and Node 22. Every service
boots locally on a laptop without external infrastructure other than a
Postgres container.

## Getting set up

Install `uv` for Python dependency management and `pnpm` for the
TypeScript packages. Clone the monorepo and run `make bootstrap`; the
target installs every language toolchain, runs database migrations
against a local Postgres container, and seeds fixtures.

The bootstrap target is idempotent. Re-run it whenever a dependency
manifest changes.

## Local services

Local development uses `docker compose` to run Postgres, Redis, and a
single in-memory NATS broker. The compose file lives at
`infra/local/docker-compose.yml`; `make up` and `make down` wrap it so
you do not need to remember the file path.

The frontend talks to a mock API by default; flip the `USE_REAL_API`
environment variable to point at the backend services running through
compose.

## Editor configuration

The repository ships `.editorconfig`, `.vscode/settings.json`, and a
`pyrightconfig.json` so that VS Code and most JetBrains IDEs pick up
the right formatter and type checker without per-engineer tweaks.

Pyright runs in strict mode for every Python package. The
pre-commit hooks reject pushes that introduce new type errors, so run
`uv run pyright` locally before you push.
