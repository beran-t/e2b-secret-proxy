"""
Integration test for the two-sandbox secret proxy architecture.

Architecture:
  App Sandbox (sandbox-egress-header)  -->  Proxy Sandbox (secret-proxy)
       curl https://proxy-url/http://target/path
       [egress adds X-Sandbox-Id]

  The proxy is accessed via its public URL in reverse-proxy mode:
  the target URL is embedded in the request path. The egress template
  on the app sandbox injects X-Sandbox-Id, which the proxy verifies.

Tests:
1. Header injection via two-sandbox path
2. Mock secret rewrite
3. Non-matching host passthrough
4. Token enforcement (no valid X-Sandbox-Id = no injection)

Usage:
    source .venv/bin/activate && python test-integration.py
"""

import json
import time
from e2b_code_interpreter import Sandbox

REAL_SECRET = "real-api-key-supersecret-abc123"
MOCK_SECRET = "MOCK_TOKEN_12345"

# Step 1: Create proxy sandbox and get its public URL
print("Creating proxy sandbox...")
proxy_sandbox = Sandbox.create(template="secret-proxy", timeout=120)
proxy_id = proxy_sandbox.sandbox_id
proxy_host = proxy_sandbox.get_host(3128)
proxy_url = f"https://{proxy_host}"
print(f"Proxy sandbox: {proxy_id}")
print(f"Proxy URL: {proxy_url}")

try:
    # Step 2: Create app sandbox from sandbox-egress-header
    print("\nCreating app sandbox from sandbox-egress-header...")
    app_sandbox = Sandbox.create(
        template="tomasberan/sandbox-egress-header",
        timeout=120,
    )
    app_id = app_sandbox.sandbox_id
    print(f"App sandbox: {app_id}")

    try:
        # Step 3: Write proxy config with app sandbox's ID as token
        proxy_config = {
            "token": app_id,
            "rules": [
                {
                    "match": "httpbin.org",
                    "headers": {
                        "Authorization": f"Bearer {REAL_SECRET}",
                        "X-Custom-Header": "injected-by-proxy",
                    },
                },
            ],
        }
        proxy_sandbox.files.write("/etc/proxy/config.json", json.dumps(proxy_config))
        print(f"Proxy config written (token={app_id}), waiting for reload...")
        time.sleep(3)

        # Test 1: Header injection via reverse proxy mode
        # App sandbox sends: GET /http://httpbin.org/headers to proxy URL
        # Egress adds X-Sandbox-Id → proxy verifies → injects headers
        print("\n--- Test 1: Header injection through proxy ---")
        result = app_sandbox.commands.run(
            f"curl -s {proxy_url}/proxy/http/httpbin.org/headers",
            timeout=30,
        )
        print("Response:", result.stdout[:500])
        assert "injected-by-proxy" in result.stdout, "X-Custom-Header not injected"
        assert REAL_SECRET in result.stdout, "Real secret not injected"
        assert "X-Sandbox-Id" not in result.stdout, "X-Sandbox-Id should be stripped"
        print("PASS: Headers injected via two-sandbox path")

        # Test 2: Mock secret gets overwritten
        print("\n--- Test 2: Mock secret rewrite ---")
        result = app_sandbox.commands.run(
            f'curl -s -H "Authorization: Bearer {MOCK_SECRET}" '
            f'{proxy_url}/proxy/http/httpbin.org/headers',
            timeout=30,
        )
        print("Response:", result.stdout[:500])
        assert MOCK_SECRET not in result.stdout, "Mock secret should be overwritten"
        assert REAL_SECRET in result.stdout, "Real secret should be present"
        print("PASS: Mock secret rewritten")

        # Test 3: Non-matching host passes through
        print("\n--- Test 3: Non-matching host passthrough ---")
        result = app_sandbox.commands.run(
            f'curl -s {proxy_url}/proxy/http/example.com -o /dev/null -w "%{{http_code}}"',
            timeout=30,
        )
        print("HTTP status:", result.stdout)
        assert result.stdout.strip() in ("200", "301", "302"), f"Unexpected: {result.stdout}"
        print("PASS: Non-matching host passed through")

        # Test 4: Token enforcement — request without valid X-Sandbox-Id
        # Use curl from proxy sandbox (no egress header) via its own localhost
        print("\n--- Test 4: Token enforcement ---")
        result = proxy_sandbox.commands.run(
            "curl -s http://localhost:3128/proxy/http/httpbin.org/headers",
            timeout=30,
        )
        print("Response:", result.stdout[:500])
        assert "injected-by-proxy" not in result.stdout, \
            "Headers should NOT be injected without valid X-Sandbox-Id"
        print("PASS: Token verification prevents unauthorized injection")

        print("\n=== All two-sandbox integration tests passed ===")

    finally:
        app_sandbox.kill()
        print("App sandbox killed.")

finally:
    proxy_sandbox.kill()
    print("Proxy sandbox killed.")
