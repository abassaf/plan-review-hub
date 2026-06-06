# API rate limiting — proposal

## Summary

Add sliding-window rate limiting middleware to the API. Exceeded limits return
`429 Too Many Requests` with a `Retry-After` header. Quotas are configurable
per-route and per-tenant without a deployment.

## Algorithm

**Sliding window** (not fixed window) — avoids the burst problem at window boundaries.
Each counter key stores a sorted set of timestamps in Redis; the middleware:

1. Removes timestamps older than `windowMs`.
2. Counts remaining entries.
3. If count >= limit: returns 429 + `Retry-After`.
4. Otherwise: adds current timestamp and proceeds.

## Response headers

All API responses (within quota or not) include:

```
X-RateLimit-Limit:     1000
X-RateLimit-Remaining: 847
X-RateLimit-Reset:     1735689600   (Unix timestamp of next window reset)
Retry-After:           42           (only on 429 responses)
```

## Quota configuration

Quotas are read from environment variables / config at startup and can be
overridden per-tenant in the database:

```json
{
  "defaultQuota": { "requests": 1000, "windowMs": 60000 },
  "routes": {
    "POST /v1/bulk-export": { "requests": 10, "windowMs": 60000 }
  }
}
```

## Bypass for internal calls

Service-to-service calls authenticated with a shared `X-Internal-Token` header
bypass rate limiting entirely. This header must never be exposed to external clients.
