"""
Build the E2B sandbox template for the secret proxy.

Usage:
    E2B_API_KEY=... python proxy/build-template.py

Run from the project root directory so that the copy() path resolves correctly.
"""

from e2b import Template, wait_for_port, default_build_logger

template = (
    Template()
    .from_node_image("22")
    .copy("./secret-proxy.js", "/opt/proxy/secret-proxy.js")
    .run_cmd(["mkdir -p /etc/proxy", "cd /opt/proxy && npm install minimatch"], user="root")
    .set_start_cmd("node /opt/proxy/secret-proxy.js", wait_for_port(3128))
)

TEMPLATE_NAME = "secret-proxy"

print(f"Building template: {TEMPLATE_NAME}")
Template.build(
    template,
    TEMPLATE_NAME,
    on_build_logs=default_build_logger(),
)
print("Template built successfully.")
