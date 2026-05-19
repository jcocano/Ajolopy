# AJ-84 — Refresh 5 broken third-party links

> Tracked in [`board.json`](../board.json) as `AJ-84`. Status, owner,
> branch, and dependencies live there.
>
> Type: `fix` (docs). Milestone: `v0.1`. Priority: `p0`.

## What

Vendor doc reorganizations since the URLs were written returned 404
for all five third-party links surfaced by the AJ-79 smoke pass.

## Fix

Each link replaced with the closest topical equivalent on the same
vendor domain (except Langfuse, which consolidated its OpenTelemetry
docs; that one now points to the upstream OpenTelemetry spec
Langfuse itself references):

- `README.md`: `modelcontextprotocol/servers/tree/main/src/github` →
  `github/github-mcp-server` (official, supported replacement
  developed by GitHub with Anthropic).
- `docs/recipes/observability/grafana.md`:
  `tempo/latest/send-data/otlp/` → `tempo/latest/configuration/`.
- `docs/recipes/observability/honeycomb.md`:
  `investigate/bubbleup/` → `investigate/analyze/identify-outliers`
  (renamed, same feature).
- `docs/recipes/observability/langfuse.md`:
  `langfuse.com/docs/opentelemetry/gen-ai` →
  `opentelemetry.io/docs/specs/semconv/gen-ai/`.
- `docs/recipes/observability/sentry.md`:
  `data-management-concepts/scrubbing/` →
  `security-legal-pii/scrubbing/`.

## Acceptance criteria

- [x] All five replacement URLs return HTTP 200.
- [x] Link labels updated when the destination's topic name changed
      (MCP github server, Langfuse → OpenTelemetry).

## Shipped

PR #141 — commit `092d409` — released in `v0.1.4`.
