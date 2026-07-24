# Toss Securities external API contract

This directory pins the server-owned Toss Securities OpenAPI contract and a deliberately smaller
read-only allowlist for this project.

Files:

- `openapi.json`: canonical upstream OpenAPI snapshot.
- `lock.json`: upstream version, fetch time, counts, and SHA-256 hashes.
- `read-only-operations.json`: the only official Toss operations eligible for collectors.
- `wts-read-only-operations.json`: reviewed WTS research operations, including host,
  auth mode, evidence grade, exposure policy, and exact request-field allowlists.

Update the snapshot with:

```bash
node scripts/sync_toss_openapi.mjs
node --test test/contract/toss-openapi-snapshot.test.mjs
```

Safety boundary:

- The snapshot contains account and order documentation because it mirrors the official contract.
- The collector allowlist contains only account-independent market-data `GET` operations.
- Adding any operation to the allowlist requires an explicit code review. Never auto-admit newly
  published paths.
- Credentials must stay in environment variables and must never be written into fixtures or this
  directory.
- WTS community responses are `aggregate_only`; raw text and author/profile identifiers must never
  leave the aggregate collector.
- WTS guest-only operations accept only the documented public guest headers. Login cookies,
  account authorization, holdings, and order operations are not eligible tools.

Upstream source: <https://openapi.tossinvest.com/openapi-docs/latest/openapi.json>
