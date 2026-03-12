"""
Example: Two-sandbox architecture for secret proxy.

Sandbox 1 (proxy): Runs the secret proxy, exposed via public URL.
Sandbox 2 (app): User code runs here, sends requests to proxy URL.

The app sandbox's egress template injects X-Sandbox-Id into all outgoing
requests. The proxy verifies this before injecting secrets.

Usage:
    E2B_API_KEY=... OPENAI_API_KEY=... python proxy/example-usage.py
"""

import json
import os
import time
from e2b_code_interpreter import Sandbox

OPENAI_KEY = os.environ["OPENAI_API_KEY"]

# 1. Create proxy sandbox and get its public URL
proxy_sandbox = Sandbox.create(template="secret-proxy", timeout=300)
proxy_host = proxy_sandbox.get_host(3128)
proxy_url = f"https://{proxy_host}"
print(f"Proxy sandbox: {proxy_sandbox.sandbox_id}")
print(f"Proxy URL: {proxy_url}")

# 2. Create app sandbox (sandbox-egress-header injects X-Sandbox-Id)
app_sandbox = Sandbox.create(template="tomasberan/sandbox-egress-header", timeout=300)
print(f"App sandbox: {app_sandbox.sandbox_id}")

# 3. Configure proxy with app sandbox's ID as token
proxy_sandbox.files.write("/etc/proxy/config.json", json.dumps({
    "token": app_sandbox.sandbox_id,
    "rules": [{
        "match": "api.openai.com",
        "headers": {"Authorization": f"Bearer {OPENAI_KEY}"},
    }],
}))
time.sleep(3)

try:
    # App code uses the API with a mock key — proxy rewrites it
    result = app_sandbox.commands.run(
        f'curl -s '
        f'-H "Authorization: Bearer MOCK_KEY" '
        f'{proxy_url}/proxy/http/api.openai.com/v1/models | head -c 300',
        timeout=30,
    )
    print("Response:", result.stdout)
    if result.stderr:
        print("Stderr:", result.stderr)

finally:
    app_sandbox.kill()
    proxy_sandbox.kill()
    print("Both sandboxes killed.")
