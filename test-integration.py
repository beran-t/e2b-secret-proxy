"""
Integration test for the secret proxy template.

Tests:
1. Header injection with sandbox ID verification
2. Mock secret gets rewritten to real secret
3. Requests WITHOUT the correct sandbox ID don't get secrets
4. Non-matching hosts pass through unchanged

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
    # Config uses the sandbox ID as the verification token.
    # Only requests that include X-Sandbox-Id: <sandbox_id> get secrets injected.
    proxy_config = {
        "token": sandbox_id,
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
    print("Config written (token = sandbox ID), waiting for reload...")
    time.sleep(3)

    # Test 1: Verified request — sandbox ID matches, headers get injected
    print("\n--- Test 1: Verified request (correct sandbox ID) ---")
    result = sandbox.commands.run(
        f'curl -s -x http://localhost:3128 '
        f'-H "X-Sandbox-Id: {sandbox_id}" '
        f'http://httpbin.org/headers',
        timeout=30,
    )
    print("Response:", result.stdout[:500])
    assert "injected-by-proxy" in result.stdout, "X-Custom-Header not injected"
    assert REAL_SECRET in result.stdout, "Real secret not injected"
    assert "X-Sandbox-Id" not in result.stdout, "Sandbox ID should be stripped before forwarding"
    print("PASS: Headers injected for verified request")

    # Test 2: Mock secret gets overwritten (with correct sandbox ID)
    print("\n--- Test 2: Mock secret rewrite ---")
    result = sandbox.commands.run(
        f'curl -s -x http://localhost:3128 '
        f'-H "X-Sandbox-Id: {sandbox_id}" '
        f'-H "Authorization: Bearer {MOCK_SECRET}" '
        f'http://httpbin.org/headers',
        timeout=30,
    )
    print("Response:", result.stdout[:500])
    assert MOCK_SECRET not in result.stdout, "Mock secret should be overwritten"
    assert REAL_SECRET in result.stdout, "Real secret should be present"
    print("PASS: Mock secret rewritten to real secret")

    # Test 3: Unverified request — wrong/missing sandbox ID, NO injection
    print("\n--- Test 3: Unverified request (wrong sandbox ID) ---")
    result = sandbox.commands.run(
        f'curl -s -x http://localhost:3128 '
        f'-H "X-Sandbox-Id: wrong-id" '
        f'-H "Authorization: Bearer {MOCK_SECRET}" '
        f'http://httpbin.org/headers',
        timeout=30,
    )
    print("Response:", result.stdout[:500])
    assert REAL_SECRET not in result.stdout, "Real secret should NOT be injected for wrong ID"
    assert MOCK_SECRET in result.stdout, "Mock secret should pass through unchanged"
    print("PASS: Unverified request did NOT get secrets")

    # Test 4: No sandbox ID header at all — no injection
    print("\n--- Test 4: No sandbox ID header ---")
    result = sandbox.commands.run(
        f'curl -s -x http://localhost:3128 '
        f'-H "Authorization: Bearer {MOCK_SECRET}" '
        f'http://httpbin.org/headers',
        timeout=30,
    )
    print("Response:", result.stdout[:500])
    assert REAL_SECRET not in result.stdout, "Real secret should NOT be injected without ID"
    print("PASS: No sandbox ID = no injection")

    # Test 5: Non-matching host passes through
    print("\n--- Test 5: Non-matching host passthrough ---")
    result = sandbox.commands.run(
        f'curl -s -x http://localhost:3128 '
        f'-H "X-Sandbox-Id: {sandbox_id}" '
        f'http://example.com -o /dev/null -w "%{{http_code}}"',
        timeout=30,
    )
    print("HTTP status:", result.stdout)
    assert result.stdout.strip() in ("200", "301", "302"), f"Unexpected status: {result.stdout}"
    print("PASS: Non-matching host passed through")

    print("\n=== All 5 integration tests passed ===")

finally:
    sandbox.kill()
    print("Sandbox killed.")
