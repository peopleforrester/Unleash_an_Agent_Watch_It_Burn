# Vendored upstream schemas

Each file here is an unmodified copy of a schema published by the project it names, kept so the
offline render gate can check our configuration without a network call and without a validator
dependency.

| File | Source | Fetched |
|---|---|---|
| `agentgateway-v1.5.0-config.json` | `https://raw.githubusercontent.com/agentgateway/agentgateway/v1.5.0/schema/config.json` | 2026-09-21 |

Re-fetch when the pinned version changes, in the same commit that changes the image tag. The file is
byte-for-byte upstream: verify with

```bash
curl -sSL https://raw.githubusercontent.com/agentgateway/agentgateway/v1.5.0/schema/config.json \
  | diff - verify/schemas/agentgateway-v1.5.0-config.json && echo identical
```
