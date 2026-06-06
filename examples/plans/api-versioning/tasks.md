# API versioning — task breakdown

## Phase 1: routing infrastructure

- [x] Add `src/middleware/version-prefix.ts` — strips `/v1` from path before dispatch
- [x] Register middleware in app bootstrap before auth middleware
- [ ] Add 301-redirect handler for `/api/*` → `/v1/*`
- [ ] Add `Deprecation` + `Sunset` headers to the redirect response

## Phase 2: OpenAPI spec

- [ ] Update base path in `openapi.yaml` from `/api` to `/v1`
- [ ] Regenerate client types from updated spec
- [ ] Add CI step: `grep -r '"/api/' openapi.yaml` must return no matches

## Phase 3: tests

- [ ] Unit test: version middleware strips prefix and passes correct path to handler
- [ ] Integration test: `GET /v1/healthz` returns 200
- [ ] Integration test: `GET /api/healthz` returns 301 with `Location: /v1/healthz`
- [ ] Integration test: redirect response includes `Deprecation` header

## Phase 4: documentation

- [ ] Update README API reference section with `/v1/` prefix examples
- [ ] Add migration guide: `docs/api-migration-v1.md`
- [ ] Announce in CHANGELOG
