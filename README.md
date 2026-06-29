# Milesight Gateway MCP Server

An [MCP](https://modelcontextprotocol.io) server that exposes the **Milesight
LoRaWAN gateway HTTP API** as tools, so an MCP client (Claude Code, Claude
Desktop, etc.) can manage applications, devices, profiles, multicast groups and
downlinks on a Milesight UG-series gateway.

It talks to the gateway's embedded network server over HTTPS (port 8080),
handling the firmware's AES-encrypted login and JWT bearer-token auth
automatically.

## Features

One tool per action across the gateway API surface:

- **Applications** — list / get / create / update / delete
- **Devices** — list / get / create / update / delete
- **Device profiles** — list / get / create / update / delete
- **Multicast groups** — list / get / create / delete, list/add/remove members
- **Downlinks** — enqueue / list / flush for both devices and multicast groups
- **Gateways** — list
- **Packets** — list / clear the frame log
- **Payload codecs** — list
- **Settings** — network-server settings, packet-forwarder network servers

## Requirements

- Python ≥ 3.10
- Network access to a Milesight gateway (firmware that uses AES login, e.g.
  60.0.0.42-r5 / 56.0.0.4 and later)

## Install

With [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

## Configure

Copy `.env.example` to `.env` and fill in your gateway details:

```bash
MILESIGHT_HOST=192.168.1.1
MILESIGHT_PORT=8080
MILESIGHT_USER=admin
MILESIGHT_PASSWORD=your-password
MILESIGHT_ORG_ID=1
MILESIGHT_VERIFY_TLS=false
```

`.env` is gitignored. The server reads these from the environment, so you can
also pass them however your MCP client injects env vars.

> **TLS:** gateways ship a self-signed certificate, so verification is off by
> default. Set `MILESIGHT_VERIFY_TLS=true` only with a trusted certificate.

## Run

```bash
uv run milesight-mcp
```

The server speaks MCP over stdio.

### Claude Code / Claude Desktop

Add to your MCP client config:

```json
{
  "mcpServers": {
    "milesight": {
      "command": "uv",
      "args": ["run", "milesight-mcp"],
      "cwd": "/path/to/milesight_mcp",
      "env": {
        "MILESIGHT_HOST": "192.168.1.1",
        "MILESIGHT_USER": "admin",
        "MILESIGHT_PASSWORD": "your-password"
      }
    }
  }
}
```

## Live smoke test

Runs read-only checks against the configured gateway (no writes):

```bash
uv run python test_live.py
```

## How auth works

The gateway login endpoint expects the password AES-128-CBC encrypted
(fixed key/IV from the firmware) and Base64-encoded. On success it returns a JWT
valid for 24 hours, sent as `Authorization: Bearer <jwt>` on every request. The
client caches the token, refreshes it proactively, and re-logs-in automatically
on a `401`.

## License

MIT
