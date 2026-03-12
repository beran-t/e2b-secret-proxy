# E2B Secret Proxy

An HTTP proxy that injects auth headers into outgoing requests from [E2B](https://e2b.dev) sandboxes. Sandbox code uses mock/placeholder tokens — the proxy rewrites them with real secrets. Each sandbox is verified by its unique ID before secrets are injected.

> **This repo is a working demo.** The proxy runs inside the sandbox for simplicity. In production, it would run as a standalone service (see [Production Architecture](#production-architecture)).

## How It Works

```
Sandbox Code                     Proxy                          Target API
     |                            |                                |
     |-- GET /v1/models --------->|                                |
     |   Authorization: MOCK      |                                |
     |   X-Sandbox-Id: abc123     |                                |
     |                            |-- verify sandbox ID            |
     |                            |-- rewrite Authorization ------>|
     |                            |   Authorization: Bearer sk-... |
     |                            |                                |
     |<-- response ---------------|<-- response -------------------|
```

1. Sandbox sends a request with a mock token and its sandbox ID
2. Proxy verifies the sandbox ID matches the configured token
3. If verified, proxy rewrites headers with real secrets and forwards
4. If not verified, request passes through unchanged (no secrets leaked)
5. The `X-Sandbox-Id` header is stripped before forwarding — the target API never sees it

## Quick Start

### 1. Install

```bash
git clone https://github.com/beran-t/e2b-secret-proxy.git
cd e2b-secret-proxy
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Build the template (one-time)

```bash
E2B_API_KEY=<your-key> python build-template.py
```

### 3. Run the tests

```bash
E2B_API_KEY=<your-key> python test-integration.py
```

This creates a sandbox, configures the proxy with the sandbox ID as the verification token, and runs 5 tests:

| Test | What it checks |
|------|---------------|
| 1 | Correct sandbox ID → headers injected |
| 2 | Mock secret gets overwritten with real secret |
| 3 | Wrong sandbox ID → secrets NOT injected |
| 4 | Missing sandbox ID → secrets NOT injected |
| 5 | Non-matching host → passes through unchanged |

## Usage

```python
import json, time
from e2b_code_interpreter import Sandbox

sandbox = Sandbox.create(template="secret-proxy", timeout=120)

# Configure: use sandbox ID as verification token
sandbox.files.write("/etc/proxy/config.json", json.dumps({
    "token": sandbox.sandbox_id,
    "rules": [{
        "match": "api.openai.com",
        "headers": {"Authorization": "Bearer sk-real-secret-key"}
    }]
}))
time.sleep(3)  # proxy auto-detects config within ~2s

# Sandbox code includes its ID — proxy verifies and injects real secret
result = sandbox.commands.run(
    f'curl -s -x http://localhost:3128 '
    f'-H "X-Sandbox-Id: {sandbox.sandbox_id}" '
    f'-H "Authorization: Bearer MOCK" '
    f'http://api.openai.com/v1/models'
)
print(result.stdout)
sandbox.kill()
```

## Config Format

```json
{
  "token": "sandbox-id-or-any-secret",
  "rules": [
    {
      "match": "api.openai.com",
      "headers": { "Authorization": "Bearer sk-..." }
    },
    {
      "match": "*.amazonaws.com",
      "headers": { "Authorization": "AWS4-HMAC-SHA256 ..." }
    }
  ]
}
```

- **`token`** (optional) — if set, requests must include `X-Sandbox-Id` header matching this value to get secrets injected. Unverified requests pass through without injection.
- **`match`** — glob pattern for the target hostname (`*` = one segment, `**` = any depth)
- **`headers`** — injected into (or overwrite) the outgoing request headers

## Production Architecture

This demo runs the proxy **inside** the sandbox for simplicity. In production, the proxy runs as a **separate service** between the sandboxes and the internet:

```
┌─────────────┐
│  Sandbox A  │──┐
│  (no secrets)│  │    ┌──────────────┐     ┌─────────────┐
└─────────────┘  ├───→│ Secret Proxy │────→│ Target APIs │
┌─────────────┐  │    │ (standalone) │     └─────────────┘
│  Sandbox B  │──┘    └──────────────┘
│  (no secrets)│           │
└─────────────┘      Verifies sandbox ID,
                     injects per-sandbox secrets
```

**What changes in production:**
- The proxy runs on its own server (not inside a sandbox)
- Each sandbox routes traffic through the proxy via `HTTP_PROXY` env var
- The proxy config maps sandbox IDs to their specific secrets
- Sandbox code includes `X-Sandbox-Id` in every request — the proxy uses this to look up which secrets to inject
- The proxy strips `X-Sandbox-Id` before forwarding so target APIs never see it

**What stays the same:**
- The proxy code (`secret-proxy.js`) works as-is — just change the listen address from `127.0.0.1` to `0.0.0.0`
- The config format is identical
- The verification flow is identical

## Files

| File | What it does |
|------|-------------|
| `secret-proxy.js` | The proxy server (Node.js, zero dependencies) |
| `start-proxy.sh` | Boot wrapper for E2B template |
| `build-template.py` | Builds the E2B sandbox template |
| `test-integration.py` | 5 end-to-end tests against httpbin.org |
| `example-usage.py` | Example with OpenAI API |
