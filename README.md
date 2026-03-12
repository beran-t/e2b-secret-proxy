# E2B Secret Proxy

An HTTP proxy that injects auth headers into outgoing requests from [E2B](https://e2b.dev) sandboxes. Sandbox code uses mock/placeholder tokens — the proxy rewrites them with real secrets. Secrets never appear in user code, LLM-generated code, or application logs.

## How It Works

```
Sandbox Code                     Proxy                          Target API
     |                            |                                |
     |-- GET /v1/models --------->|                                |
     |   Authorization: MOCK      |                                |
     |                            |-- rewrite Authorization ------>|
     |                            |   Authorization: Bearer sk-... |
     |                            |                                |
     |<-- response ---------------|<-- response -------------------|
```

1. Proxy starts on `localhost:3128` when the sandbox boots
2. After sandbox creation, you write the proxy config with real secrets via `sandbox.files.write()`
3. Sandbox code makes HTTP requests through the proxy (using `-x http://localhost:3128`)
4. Proxy matches the target host against configured rules and injects/overwrites headers
5. Response is piped back to the sandbox unchanged

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

This creates a sandbox, configures the proxy, and runs 3 tests:

| Test | What it checks |
|------|---------------|
| 1 | Headers injected for matching host |
| 2 | Mock secret gets overwritten with real secret |
| 3 | Non-matching host passes through unchanged |

## Usage

```python
import json, time
from e2b_code_interpreter import Sandbox

sandbox = Sandbox.create(template="secret-proxy", timeout=120)

# Write config — proxy auto-detects within ~2s
sandbox.files.write("/etc/proxy/config.json", json.dumps({
    "rules": [{
        "match": "api.openai.com",
        "headers": {"Authorization": "Bearer sk-real-secret-key"}
    }]
}))
time.sleep(3)

# Sandbox code uses a mock token — proxy rewrites it
result = sandbox.commands.run(
    'curl -s -x http://localhost:3128 '
    '-H "Authorization: Bearer MOCK" '
    'http://api.openai.com/v1/models'
)
print(result.stdout)
sandbox.kill()
```

## Config Format

```json
{
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

- **`match`** — glob pattern for the target hostname (`*` = one segment, `**` = any depth)
- **`headers`** — injected into (or overwrite) the outgoing request headers

### Optional: Token Verification

Add a `token` field to require requests to include a matching `X-Sandbox-Id` header before secrets are injected:

```json
{
  "token": "sandbox-id-or-shared-secret",
  "rules": [...]
}
```

Unverified requests pass through without header injection (no secrets leaked). The `X-Sandbox-Id` header is stripped before forwarding.

### Glob Pattern Syntax

| Pattern | Matches | Example |
|---------|---------|---------|
| `api.openai.com` | Exact hostname | `api.openai.com` only |
| `*.openai.com` | Single subdomain segment | `api.openai.com`, `chat.openai.com` |
| `**.openai.com` | Any depth of subdomains | `api.openai.com`, `api.v2.openai.com` |
| `api?.example.com` | Single character wildcard | `api1.example.com` |

### Config Loading

The proxy reads config from `/etc/proxy/config.json` (preferred) or the `PROXY_CONFIG` env var. It polls the config file every 2 seconds and auto-reloads when it changes. You can also send `SIGHUP` to force a reload.

## HTTP vs HTTPS

Header injection only works for HTTP requests. HTTPS `CONNECT` tunnels pass through unchanged since the traffic is encrypted end-to-end.

| Client URL | What happens |
|------------|-------------|
| `http://api.openai.com/...` | Proxy intercepts, injects headers, forwards |
| `https://api.openai.com/...` via `HTTPS_PROXY` | `CONNECT` tunnel — no injection |

**Recommendation**: Use `http://` URLs in sandbox code with `-x http://localhost:3128`. The proxy handles the upstream connection.

## Files

| File | What it does |
|------|-------------|
| `secret-proxy.js` | The proxy server (Node.js, zero dependencies) |
| `start-proxy.sh` | Boot wrapper for E2B template |
| `build-template.py` | Builds the E2B sandbox template |
| `test-integration.py` | 3 end-to-end tests against httpbin.org |
| `example-usage.py` | Example with OpenAI API |
