"""
Integration test for the secret proxy template.

Tests:
1. Header injection — proxy injects configured headers into matching requests
2. Mock secret rewrite — existing Authorization header gets overwritten
3. Non-matching hosts pass through unchanged

Usage:
    source .venv/bin/activate && python test-integration.py
"""

import json
import time
from e2b_code_interpreter import Sandbox

MOCK_SECRET = "MOCK_TOKEN_12345"
REAL_SECRET = "real-api-key-supersecret-abc123"

print("Creating sandbox from secret-proxy...")
sandbox = Sandbox.create(
    template="secret-proxy",
    timeout=120,
)
sandbox_id = sandbox.sandbox_id
print(f"Sandbox created: {sandbox_id}")

try:
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

    config_json = json.dumps(proxy_config)
    sandbox.files.write("/etc/proxy/config.json", config_json)
    print("Config written, waiting for reload...")
    time.sleep(3)

    # Test 1: Headers get injected for matching host
    print("\n--- Test 1: Header injection ---")
    result = sandbox.commands.run(
        "curl -s -x http://localhost:3128 http://httpbin.org/headers",
        timeout=30,
    )
    print("Response:", result.stdout[:500])
    assert "injected-by-proxy" in result.stdout, "X-Custom-Header not injected"
    assert REAL_SECRET in result.stdout, "Real secret not injected"
    print("PASS: Headers injected correctly")

    # Test 2: Mock secret gets overwritten
    print("\n--- Test 2: Mock secret rewrite ---")
    result = sandbox.commands.run(
        f'curl -s -x http://localhost:3128 '
        f'-H "Authorization: Bearer {MOCK_SECRET}" '
        f'http://httpbin.org/headers',
        timeout=30,
    )
    print("Response:", result.stdout[:500])
    assert MOCK_SECRET not in result.stdout, "Mock secret should be overwritten"
    assert REAL_SECRET in result.stdout, "Real secret should be present"
    print("PASS: Mock secret rewritten to real secret")

    # Test 3: Non-matching host passes through
    print("\n--- Test 3: Non-matching host passthrough ---")
    result = sandbox.commands.run(
        'curl -s -x http://localhost:3128 http://example.com -o /dev/null -w "%{http_code}"',
        timeout=30,
    )
    print("HTTP status:", result.stdout)
    assert result.stdout.strip() in ("200", "301", "302"), f"Unexpected status: {result.stdout}"
    print("PASS: Non-matching host passed through")

    print("\n=== All integration tests passed ===")

finally:
    sandbox.kill()
    print("Sandbox killed.")
