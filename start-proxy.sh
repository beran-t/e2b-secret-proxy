#!/bin/bash
# Start script for the secret proxy inside E2B sandbox.
# Handles snapshot-restore: kills any leftover proxy from template build,
# writes fresh config from PROXY_CONFIG env var, then starts the proxy.

# Kill any existing proxy (from template snapshot)
pkill -f "node /opt/proxy/secret-proxy.js" 2>/dev/null || true
sleep 0.3

# Write config file from env var if set
if [ -n "$PROXY_CONFIG" ]; then
  echo "$PROXY_CONFIG" > /etc/proxy/config.json
fi

# Start proxy (reads from /etc/proxy/config.json or PROXY_CONFIG env)
exec node /opt/proxy/secret-proxy.js
