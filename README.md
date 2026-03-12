# E2B Secret Proxy

An HTTP proxy that runs inside an [E2B](https://e2b.dev) sandbox and injects auth headers into outgoing requests. Sandbox code uses mock/placeholder tokens — the proxy rewrites them with real secrets automatically.

```
Sandbox Code  →  Proxy (localhost:3128)  →  Target API
  (mock token)     (rewrites to real secret)
```

## Quick Start

### 1. Install dependencies

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Build the template

```bash
E2B_API_KEY=<your-key> python build-template.py
```

This builds an E2B sandbox template called `secret-proxy` with Node.js and the proxy pre-installed. Only needs to be done once.

### 3. Run the test

```bash
E2B_API_KEY=<your-key> python test-integration.py
```

This creates a sandbox, configures the proxy to inject headers for `httpbin.org`, and verifies:
- Headers get injected for matching hosts
- Mock secrets get overwritten with real ones
- Non-matching requests pass through unchanged

## How to Use

```python
import json, time
from e2b_code_interpreter import Sandbox

# 1. Create sandbox
sandbox = Sandbox.create(template="secret-proxy", timeout=120)

# 2. Write proxy rules (maps host patterns → headers to inject)
sandbox.files.write("/etc/proxy/config.json", json.dumps({
    "rules": [{
        "match": "api.openai.com",
        "headers": {"Authorization": "Bearer sk-real-secret-key"}
    }]
}))
time.sleep(3)  # proxy auto-detects config within ~2s

# 3. Sandbox code uses mock tokens — proxy rewrites them
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

**`match`** — glob pattern for the target hostname:

| Pattern | Matches |
|---------|---------|
| `api.openai.com` | Exact match only |
| `*.openai.com` | `api.openai.com`, `chat.openai.com` |
| `**.openai.com` | Any depth: `api.v2.openai.com` |

**`headers`** — injected into (or overwrite) the outgoing request headers.

## Files

| File | What it does |
|------|-------------|
| `secret-proxy.js` | The proxy server (Node.js, no dependencies) |
| `start-proxy.sh` | Boot wrapper for E2B template |
| `build-template.py` | Builds the E2B template |
| `test-integration.py` | End-to-end test against httpbin.org |
| `example-usage.py` | Example with OpenAI API |

## Notes

- Header injection works for **HTTP requests**. For HTTPS targets, use `http://` in the URL — the proxy upgrades to HTTPS upstream.
- The proxy polls `/etc/proxy/config.json` every 2s and auto-reloads on changes.
- Secrets only exist inside the sandbox's config file — never in env vars or logs.
