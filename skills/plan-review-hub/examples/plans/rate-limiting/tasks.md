# API rate limiting — task breakdown

## Phase 1: Redis client and core algorithm

- [x] Add `redis` (or `ioredis`) to dependencies
- [x] Create `src/lib/redis.ts` — singleton client with connection-error handling
- [ ] Implement `src/middleware/rate-limit.ts` — sliding-window algorithm
- [ ] Unit test: counter increments correctly on each request
- [ ] Unit test: window slides (old timestamps removed)
- [ ] Unit test: returns `{ limited: true, retryAfter }` when quota exceeded

## Phase 2: middleware integration

- [ ] Register rate-limit middleware in app bootstrap
- [ ] Add per-route overrides via route metadata (`rateLimit: { requests, windowMs }`)
- [ ] Attach `X-RateLimit-*` headers to all responses
- [ ] Return `429` with `Retry-After` when limited

## Phase 3: per-tenant quotas

- [ ] Add `quotaOverride` column to `api_keys` table (nullable JSON)
- [ ] Middleware reads per-key override; falls back to global default
- [ ] Migration: `20260101_add_quota_override_to_api_keys.sql`

## Phase 4: tests

- [ ] Integration test: 1001st request in a 60s window returns 429
- [ ] Integration test: `Retry-After` header is a positive integer
- [ ] Integration test: internal token bypasses rate limit
- [ ] Load test: 5 000 concurrent requests do not crash the Redis client

## Phase 5: observability

- [ ] Log rate-limited requests at WARN level with `{ ip, token, path, limit }`
- [ ] Add Prometheus counter `api_rate_limited_total` labelled by `{route}`
- [ ] Add runbook entry to `docs/runbooks/rate-limiting.md`
