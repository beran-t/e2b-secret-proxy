"""
Example: Using the secret proxy sandbox to make authenticated API calls
without exposing secrets to user code.

The sandbox code sends requests with mock/placeholder tokens. The proxy
intercepts them and rewrites the headers with real secrets.

Usage:
    E2B_API_KEY=... OPENAI_API_KEY=... python example-usage.py
"""

import json
import os
import time
from e2b_code_interpreter import Sandbox

# Define proxy rules — map target hosts to real secret headers.
# When sandbox code hits api.openai.com, the proxy injects the real key.
proxy_config = {
    "rules": [
        {
            "match": "api.openai.com",
            "headers": {
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            },
        },
    ],
}

# Create sandbox from the proxy template
sandbox = Sandbox.create(
    template="secret-proxy",
    timeout=300,
)
print("Sandbox created:", sandbox.sandbox_id)

# Write the config — the proxy picks it up automatically within ~2 seconds
sandbox.files.write("/etc/proxy/config.json", json.dumps(proxy_config))
time.sleep(3)

try:
    # Sandbox code sends a request with a MOCK token.
    # The proxy rewrites Authorization to the real OpenAI key.
    result = sandbox.commands.run(
        'curl -s -x http://localhost:3128 '
        '-H "Authorization: Bearer MOCK_KEY" '
        'http://api.openai.com/v1/models | head -c 300',
        timeout=30,
    )
    print("Response (first 300 chars):", result.stdout)
    if result.stderr:
        print("Stderr:", result.stderr)

finally:
    sandbox.kill()
    print("Sandbox killed.")
