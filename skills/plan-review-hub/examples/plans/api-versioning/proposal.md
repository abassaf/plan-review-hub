# API versioning — proposal

## Summary

Introduce a `/v1/` URL prefix across the REST API so that breaking changes can be shipped
on `/v2/` in the future without disrupting existing consumers.

## What changes

- A router middleware rewrites incoming `/v1/*` requests to the existing handlers — zero
  handler rewrite needed.
- Unversioned `/api/*` paths return a `301 → /v1/*` (or `410`, per the decision above).
- `Deprecation` and `Sunset` response headers are attached to every unversioned response.
- OpenAPI spec updated: all paths now documented under `/v1/`.
- CI smoke test added: asserts the version prefix is present on every spec path.

## What does NOT change

- Handler logic — purely a routing layer.
- Auth / session middleware — runs before versioning, unaffected.
- Database schema.
- Existing test suite (handlers still receive the same request shape after rewrite).

## Out of scope

- `/v2/` is not implemented here — only the infrastructure to support it later.
- SDK / client library updates (separate follow-up).
