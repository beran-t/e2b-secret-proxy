# Secret Proxy

An HTTP proxy that injects auth headers into outgoing requests from E2B sandboxes. Secrets live only in the proxy — sandbox user code never sees them.

## Architecture

Two sandboxes work together:

```
App Sandbox (sandbox-egress-header)
  |  curl https://proxy-url/proxy/http/api.openai.com/v1/models
  |  [egress adds X-Sandbox-Id automatically]
  v
Proxy Sandbox (secret-proxy, port 3128 exposed)
  |  verify X-Sandbox-Id → inject secret headers → strip X-Sandbox-Id
  v
Target API (api.openai.com)
```

1. **Proxy sandbox** runs the secret proxy, exposed via public URL (`get_host(3128)`)
2. **App sandbox** uses `sandbox-egress-header` template, which auto-injects `X-Sandbox-Id` on all outgoing requests
3. App sends requests to the proxy URL using reverse proxy mode: `/proxy/http/{host}/{path}`
4. Proxy verifies `X-Sandbox-Id` matches the configured token, injects secret headers, strips `X-Sandbox-Id`, and forwards

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

## Usage

```python
import json, time
from e2b_code_interpreter import Sandbox

# 1. Create proxy sandbox and get its public URL
proxy = Sandbox.create(template="secret-proxy", timeout=120)
proxy_url = f"https://{proxy.get_host(3128)}"

# 2. Create app sandbox (egress template adds X-Sandbox-Id automatically)
app = Sandbox.create(template="sandbox-egress-header", timeout=120)

# 3. Configure proxy — use app sandbox's ID as verification token
proxy.files.write("/etc/proxy/config.json", json.dumps({
    "token": app.sandbox_id,
    "rules": [{
        "match": "api.openai.com",
        "headers": {"Authorization": "Bearer sk-real-secret-key"}
    }]
}))
time.sleep(3)

# 4. App code uses the API — proxy injects real key
result = app.commands.run(
    f'curl -s -H "Authorization: Bearer MOCK" '
    f'{proxy_url}/proxy/http/api.openai.com/v1/models'
)
print(result.stdout)

app.kill()
proxy.kill()
```

## URL Format

Target URL is encoded in the request path:

```bash
curl https://proxy-url/proxy/http/httpbin.org/headers
curl https://proxy-url/proxy/https/api.openai.com/v1/models
```

Pattern: `/proxy/{http|https}/{host}/{path}`

## Config Format

```json
{
  "token": "app-sandbox-id",
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

- **`token`** (optional) — if set, requests must include `X-Sandbox-Id` header matching this value. The `sandbox-egress-header` template adds this automatically.
- **`match`** — glob pattern for the target hostname (`*` = one segment, `**` = any depth)
- **`headers`** — injected into (or overwrite) the outgoing request headers

### Glob Pattern Syntax

| Pattern | Matches | Example |
|---------|---------|---------|
| `api.openai.com` | Exact hostname | `api.openai.com` only |
| `*.openai.com` | Single subdomain segment | `api.openai.com`, `chat.openai.com` |
| `**.openai.com` | Any depth of subdomains | `api.openai.com`, `api.v2.openai.com` |
| `api?.example.com` | Single character wildcard | `api1.example.com` |

### Config Loading

The proxy reads config from `/etc/proxy/config.json` (preferred) or the `PROXY_CONFIG` env var. It polls the config file every 2 seconds and auto-reloads when it changes.

## Security Model

- Secrets exist only in the proxy sandbox's config file — never in the app sandbox
- `X-Sandbox-Id` verification ensures only the authorized app sandbox gets secret injection
- The `X-Sandbox-Id` header is stripped before forwarding to target APIs
- Requests without a valid token pass through without injection (no secrets leaked)

## Files

| File | What it does |
|------|-------------|
| `secret-proxy.js` | The proxy server (Node.js, uses [minimatch](https://www.npmjs.com/package/minimatch) for glob matching) |
| `build-template.py` | Builds the E2B sandbox template |
| `test-integration.py` | Integration test (4 tests) |
| `example-usage.py` | Example with OpenAI API |
