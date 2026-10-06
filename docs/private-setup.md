# Private runtime

The official [secure MCP tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) describes the OpenAI organization, ChatGPT workspace, tunnel, and runtime-key requirements.

The OpenAI key authenticates the tunnel client to OpenAI. The Canvas token authenticates Canvas API reads. Neither credential belongs in the plugin manifest, tool parameters, GitHub, screenshots, or chat messages. Tool results are sent to ChatGPT when invoked, so the user's ChatGPT data settings apply.

The runtime script saves configuration under `data/private-tunnel/`, ignored by Git. The official client also keeps its own managed-runtime state and logs in the operating system's application-support directory. Do not delete either while the runtime is in use. `status` checks both local readiness and a successful OpenAI control-plane poll. ChatGPT tool use is the final end-to-end check.

The first start needs `CANVAS_BASE_URL`, `CANVAS_TOKEN_FILE`, and the official client path. Subsequent starts reuse the saved configuration. Download the client from its official releases and verify the release checksum. No automatic binary downloader is included in this project.

If files fail with “outside the configured host allowlist,” inspect only the hostname of the Canvas-provided file redirect, verify it belongs to the institution's Canvas storage, then set `CANVAS_FILE_HOSTS` to exact trusted hostnames. Do not copy signed URLs into public reports. If a verified hostname embeds the Canvas file ID, configure that portion as `{file_id}`; the server expands it only to the requested file's ID and checks the resulting exact hostname. Wildcards are not supported. Restart after changing the saved launcher. Existing calls may need to retry during a restart.

For revoked/expired Canvas tokens, replace the local token privately. For a revoked runtime key, stop the tunnel, privately replace its key file, and restart. Preserve owner-only permissions. To remove access, disconnect the plugin in ChatGPT, stop the runtime, and revoke its dedicated OpenAI runtime key and tunnel as appropriate. Removing local files alone does not revoke remote credentials.

This setup does not install a login item or keep the computer awake. After a reboot, run `python3 scripts/tunnel.py start` from the repository. A sleeping/offline Mac cannot answer calls.
