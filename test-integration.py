"""
Integration test for the secret proxy template.

Tests:
1. Proxy picks up config written after sandbox creation
2. Proxy injects headers for matching hosts
3. Mock secret gets rewritten to real secret
4. Non-matching requests pass through unchanged

Usage:
    source .venv/bin/activate && python test-integration.py
"""

import json
import time
from e2b_code_interpreter import Sandbox

# Config: when sandbox code sends a request to httpbin.org,
# the proxy injects headers (rewriting any mock values).
MOCK_SECRET = "MOCK_TOKEN_12345"
REAL_SECRET = "real-api-key-supersecret-abc123"

proxy_config = {
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

print("Creating sandbox from secret-proxy...")
sandbox = Sandbox.create(
    template="secret-proxy",
    timeout=120,
)
print(f"Sandbox created: {sandbox.sandbox_id}")

try:
    # Write config file — the proxy polls for this every 2 seconds
    config_json = json.dumps(proxy_config)
    sandbox.files.write("/etc/proxy/config.json", config_json)
    print("Config file written, waiting for proxy to reload...")
    time.sleep(3)  # Wait for the proxy to detect the file change

    # Test 1: Header injection works
    print("\n--- Test 1: Header injection ---")
    result = sandbox.commands.run(
        "curl -s -x http://localhost:3128 http://httpbin.org/headers",
        timeout=30,
    )
    print("Response:", result.stdout[:500])
    assert "injected-by-proxy" in result.stdout, f"X-Custom-Header not found in response"
    assert REAL_SECRET in result.stdout, f"Real secret not found in response"
    print("PASS: Headers injected correctly")

    # Test 2: Mock secret gets overwritten
    print("\n--- Test 2: Mock secret rewrite ---")
    result = sandbox.commands.run(
        f'curl -s -x http://localhost:3128 -H "Authorization: Bearer {MOCK_SECRET}" http://httpbin.org/headers',
        timeout=30,
    )
    print("Response:", result.stdout[:500])
    assert MOCK_SECRET not in result.stdout, "Mock secret should have been overwritten"
    assert REAL_SECRET in result.stdout, "Real secret should be present"
    print("PASS: Mock secret rewritten to real secret")

    # Test 3: Non-matching host passes through
    print("\n--- Test 3: Non-matching passthrough ---")
    result = sandbox.commands.run(
        'curl -s -x http://localhost:3128 http://example.com -o /dev/null -w "%{http_code}"',
        timeout=30,
    )
    print("HTTP status:", result.stdout)
    assert result.stdout.strip() in ("200", "301", "302"), f"Unexpected status: {result.stdout}"
    print("PASS: Non-matching request passed through")

    print("\n=== All integration tests passed ===")

finally:
    sandbox.kill()
    print("Sandbox killed.")
