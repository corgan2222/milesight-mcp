"""Milesight LoRaWAN gateway MCP server.

Exposes the gateway HTTP API as MCP tools (one tool per action). Configuration
comes from environment variables:

    MILESIGHT_HOST       gateway IP/host (required)
    MILESIGHT_USER       login username (required)
    MILESIGHT_PASSWORD   login password (required)
    MILESIGHT_PORT       HTTPS port (default 8080)
    MILESIGHT_ORG_ID     default organizationID (default "1")
    MILESIGHT_VERIFY_TLS "true" to enable TLS verification (default off; the
                         gateway ships a self-signed certificate)
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP

from .client import MilesightClient, MilesightError

try:  # Optional convenience: load a local .env if python-dotenv is installed.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dotenv is optional at runtime
    pass

mcp = FastMCP("milesight-gateway")

_client: MilesightClient | None = None
_DEFAULT_ORG = os.environ.get("MILESIGHT_ORG_ID", "1")


def _get_client() -> MilesightClient:
    """Lazily build the shared client from the environment."""
    global _client
    if _client is None:
        host = os.environ.get("MILESIGHT_HOST")
        user = os.environ.get("MILESIGHT_USER")
        password = os.environ.get("MILESIGHT_PASSWORD")
        if not host or not user or password is None:
            raise MilesightError(
                "Missing config: set MILESIGHT_HOST, MILESIGHT_USER, "
                "MILESIGHT_PASSWORD."
            )
        port = int(os.environ.get("MILESIGHT_PORT", "8080"))
        verify = os.environ.get("MILESIGHT_VERIFY_TLS", "").lower() in (
            "1",
            "true",
            "yes",
        )
        _client = MilesightClient(
            host, user, password, port=port, verify=verify
        )
    return _client


def _org(organization_id: str | None) -> str:
    return organization_id or _DEFAULT_ORG


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


@mcp.tool
async def list_applications(
    limit: int = 100,
    offset: int = 0,
    organization_id: str | None = None,
) -> Any:
    """List LoRaWAN applications on the gateway.

    Returns ``{totalCount, result:[...]}``. Each application groups devices and
    binds a service profile.
    """
    return await _get_client().get(
        "/api/urapplications",
        params={
            "limit": limit,
            "offset": offset,
            "organizationID": _org(organization_id),
        },
    )


@mcp.tool
async def get_application(application_id: str) -> Any:
    """Get a single application by ID."""
    return await _get_client().get(f"/api/urapplications/{application_id}")


@mcp.tool
async def create_application(
    name: str,
    service_profile_id: str,
    description: str = "",
    organization_id: str | None = None,
) -> Any:
    """Create an application. Returns ``{id}``.

    ``service_profile_id`` must be an existing service-profile UUID (list them
    via the gateway's service profiles).
    """
    return await _get_client().post(
        "/api/urapplications",
        json={
            "name": name,
            "description": description,
            "organizationID": _org(organization_id),
            "serviceProfileID": service_profile_id,
        },
    )


@mcp.tool
async def update_application(
    application_id: str,
    name: str,
    service_profile_id: str,
    description: str = "",
    organization_id: str | None = None,
) -> Any:
    """Update an existing application."""
    return await _get_client().put(
        f"/api/urapplications/{application_id}",
        json={
            "name": name,
            "description": description,
            "organizationID": _org(organization_id),
            "serviceProfileID": service_profile_id,
        },
    )


@mcp.tool
async def delete_application(application_id: str) -> Any:
    """Delete an application by ID."""
    return await _get_client().delete(f"/api/urapplications/{application_id}")


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


@mcp.tool
async def list_devices(
    application_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    organization_id: str | None = None,
    search: str | None = None,
) -> Any:
    """List devices, optionally scoped to one application.

    Returns ``{devTotalCount, deviceResult:[...]}``.
    """
    return await _get_client().get(
        "/api/urdevices",
        params={
            "limit": limit,
            "offset": offset,
            "organizationID": _org(organization_id),
            "applicationID": application_id,
            "search": search,
        },
    )


async def _find_device(dev_eui: str) -> dict[str, Any]:
    """Look up a single device record via the documented LIST endpoint.

    The gateway exposes no per-DevEUI GET, so ``/api/urdevices`` is queried with
    ``search`` (which matches device name *or* DevEUI) and the result filtered
    for an exact DevEUI match. Raises :class:`MilesightError` if not found.
    """
    result = await _get_client().get(
        "/api/urdevices",
        params={
            "limit": 100,
            "offset": 0,
            "organizationID": _DEFAULT_ORG,
            "applicationID": "0",
            "search": dev_eui,
        },
    )
    devices = result.get("deviceResult") if isinstance(result, dict) else None
    for device in devices or []:
        if str(device.get("devEUI", "")).lower() == dev_eui.lower():
            return device
    raise MilesightError(f"Device not found: {dev_eui}")


@mcp.tool
async def get_device(dev_eui: str) -> Any:
    """Get a single device by its DevEUI.

    The gateway exposes no per-DevEUI GET endpoint, so this searches the device
    list and returns the matching record.
    """
    return await _find_device(dev_eui)


@mcp.tool
async def create_device(
    dev_eui: str,
    name: str,
    application_id: str,
    profile_id: str,
    description: str = "",
    app_key: str | None = None,
    dev_addr: str | None = None,
    app_s_key: str | None = None,
    nwk_s_key: str | None = None,
    f_port: int | None = None,
    payload_codec_id: str | None = None,
    skip_fcnt_check: bool = False,
) -> Any:
    """Register a new device under an application.

    ``dev_eui`` and ``application_id`` are required. For OTAA provide ``app_key``;
    for ABP provide ``dev_addr``, ``app_s_key`` and ``nwk_s_key``.
    """
    body: dict[str, Any] = {
        "devEUI": dev_eui,
        "name": name,
        "applicationID": application_id,
        "description": description,
        "profileID": profile_id,
        "skipFCntCheck": skip_fcnt_check,
    }
    optional = {
        "appKey": app_key,
        "devAddr": dev_addr,
        "appSKey": app_s_key,
        "nwkSKey": nwk_s_key,
        "fPort": f_port,
        "payloadCodecID": payload_codec_id,
    }
    body.update({k: v for k, v in optional.items() if v is not None})
    return await _get_client().post("/api/urdevices", json=body)


@mcp.tool
async def update_device(
    dev_eui: str,
    name: str | None = None,
    description: str | None = None,
    profile_id: str | None = None,
    app_key: str | None = None,
    payload_codec_id: str | None = None,
    skip_fcnt_check: bool | None = None,
    f_port: int | None = None,
) -> Any:
    """Update a device. Only the provided fields are changed (merged onto the
    device's current record).

    The gateway's update endpoint requires *all* mandatory fields in every
    request, so the current record is fetched first and the requested changes
    merged in before the full body is sent.
    """
    current = await _find_device(dev_eui)
    overrides = {
        "name": name,
        "description": description,
        "profileID": profile_id,
        "appKey": app_key,
        "payloadCodecID": payload_codec_id,
        "skipFCntCheck": skip_fcnt_check,
        "fPort": f_port,
    }
    for key, value in overrides.items():
        if value is not None:
            current[key] = value
    body: dict[str, Any] = {
        "name": current.get("name"),
        "description": current.get("description", ""),
        "applicationID": current.get("applicationID"),
        "profileID": current.get("profileID"),
        "skipFCntCheck": current.get("skipFCntCheck", False),
        "fPort": current.get("fPort"),
        "payloadCodecID": current.get("payloadCodecID"),
    }
    # OTAA devices carry an appKey; preserve it so the update does not drop it.
    if current.get("appKey"):
        body["appKey"] = current["appKey"]
    return await _get_client().put(f"/api/urdevices/{dev_eui}", json=body)


@mcp.tool
async def delete_device(dev_eui: str) -> Any:
    """Delete a device by its DevEUI."""
    return await _get_client().delete(f"/api/urdevices/{dev_eui}")


# ---------------------------------------------------------------------------
# Device profiles
# ---------------------------------------------------------------------------


@mcp.tool
async def list_profiles(
    limit: int = 100,
    offset: int = 0,
    organization_id: str | None = None,
) -> Any:
    """List device profiles. Returns ``{totalCount, result:[...]}``."""
    return await _get_client().get(
        "/api/urprofiles",
        params={
            "limit": limit,
            "offset": offset,
            "organizationID": _org(organization_id),
        },
    )


@mcp.tool
async def get_profile(profile_id: str) -> Any:
    """Get a single device profile by ID."""
    return await _get_client().get(f"/api/urprofiles/{profile_id}")


@mcp.tool
async def create_profile(
    name: str,
    profile: dict[str, Any],
    organization_id: str | None = None,
) -> Any:
    """Create a device profile.

    ``profile`` is the LoRaWAN profile object, e.g.::

        {
          "macVersion": "1.0.2", "regParamsRevision": "A",
          "rfRegion": "EU868", "maxEIRP": 16, "supportsJoin": true,
          "supportsClassC": false, "supportsClassB": false
        }
    """
    return await _get_client().post(
        "/api/urprofiles",
        json={
            "name": name,
            "organizationID": _org(organization_id),
            "profile": profile,
        },
    )


@mcp.tool
async def update_profile(
    profile_id: str,
    name: str,
    profile: dict[str, Any],
    organization_id: str | None = None,
) -> Any:
    """Update an existing device profile."""
    return await _get_client().put(
        f"/api/urprofiles/{profile_id}",
        json={
            "name": name,
            "organizationID": _org(organization_id),
            "profile": profile,
        },
    )


@mcp.tool
async def delete_profile(profile_id: str) -> Any:
    """Delete a device profile by ID."""
    return await _get_client().delete(f"/api/urprofiles/{profile_id}")


# ---------------------------------------------------------------------------
# Multicast groups
# ---------------------------------------------------------------------------


@mcp.tool
async def list_multicast_groups(
    limit: int = 100,
    offset: int = 0,
    organization_id: str | None = None,
) -> Any:
    """List multicast groups. Returns ``{totalCount, result:[...]}``."""
    return await _get_client().get(
        "/api/multicast-groups",
        params={
            "limit": limit,
            "offset": offset,
            "organizationID": _org(organization_id),
        },
    )


@mcp.tool
async def get_multicast_group(group_id: str) -> Any:
    """Get a single multicast group by ID."""
    return await _get_client().get(f"/api/multicast-groups/{group_id}")


@mcp.tool
async def create_multicast_group(
    name: str,
    mc_addr: str,
    mc_nwk_s_key: str,
    mc_app_s_key: str,
    dr: int,
    frequency: int,
    group_type: str = "CLASS_C",
    f_cnt: int = 0,
    ping_slot_period: int = 0,
    organization_id: str | None = None,
) -> Any:
    """Create a multicast group.

    ``group_type`` is ``CLASS_C`` or ``CLASS_B``. ``frequency`` is in Hz.
    """
    return await _get_client().post(
        "/api/multicast-groups",
        json={
            "multicastGroup": {
                "name": name,
                "mcAddr": mc_addr,
                "mcNwkSKey": mc_nwk_s_key,
                "mcAppSKey": mc_app_s_key,
                "fCnt": f_cnt,
                "groupType": group_type,
                "dr": dr,
                "frequency": frequency,
                "pingSlotPeriod": ping_slot_period,
                "organizationID": _org(organization_id),
            }
        },
    )


@mcp.tool
async def delete_multicast_group(group_id: str) -> Any:
    """Delete a multicast group by ID."""
    return await _get_client().delete(f"/api/multicast-groups/{group_id}")


@mcp.tool
async def list_multicast_group_devices(
    group_id: str,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List devices belonging to a multicast group."""
    return await _get_client().get(
        f"/api/multicast-groups/{group_id}/devices",
        params={"limit": limit, "offset": offset},
    )


@mcp.tool
async def add_device_to_multicast_group(group_id: str, dev_eui: str) -> Any:
    """Add a device (by DevEUI) to a multicast group."""
    return await _get_client().post(
        f"/api/multicast-groups/{group_id}/device",
        json={"devEUI": dev_eui},
    )


@mcp.tool
async def remove_device_from_multicast_group(group_id: str, dev_eui: str) -> Any:
    """Remove a device (by DevEUI) from a multicast group."""
    return await _get_client().delete(
        f"/api/multicast-groups/{group_id}/device/{dev_eui}"
    )


# ---------------------------------------------------------------------------
# Downlink queues
# ---------------------------------------------------------------------------


@mcp.tool
async def enqueue_device_downlink(
    dev_eui: str,
    data_base64: str,
    f_port: int,
    confirmed: bool = False,
) -> Any:
    """Queue a downlink payload to a device.

    ``data_base64`` is the raw frame payload, Base64-encoded. ``f_port`` is the
    LoRaWAN application port (1-233).
    """
    return await _get_client().post(
        f"/api/devices/{dev_eui}/queue",
        json={
            "confirmed": confirmed,
            "fPort": f_port,
            "data": data_base64,
        },
    )


@mcp.tool
async def get_device_downlink_queue(dev_eui: str) -> Any:
    """Get pending downlink items queued for a device."""
    return await _get_client().get(f"/api/devices/{dev_eui}/queue")


@mcp.tool
async def flush_device_downlink_queue(dev_eui: str) -> Any:
    """Delete all pending downlink items for a device."""
    return await _get_client().delete(f"/api/devices/{dev_eui}/queue")


@mcp.tool
async def enqueue_multicast_downlink(
    group_id: str,
    data_base64: str,
    f_port: int,
    f_cnt: int | None = None,
) -> Any:
    """Queue a downlink payload to a multicast group. Returns ``{fCnt}``."""
    item: dict[str, Any] = {"fPort": f_port, "data": data_base64}
    if f_cnt is not None:
        item["fCnt"] = f_cnt
    return await _get_client().post(
        f"/api/multicast-groups/{group_id}/queue",
        json={"multicastQueueItem": item},
    )


@mcp.tool
async def get_multicast_downlink_queue(group_id: str) -> Any:
    """Get pending downlink items queued for a multicast group."""
    return await _get_client().get(f"/api/multicast-groups/{group_id}/queue")


@mcp.tool
async def flush_multicast_downlink_queue(group_id: str) -> Any:
    """Delete all pending downlink items for a multicast group."""
    return await _get_client().delete(f"/api/multicast-groups/{group_id}/queue")


# ---------------------------------------------------------------------------
# Gateways, packets, codecs, settings
# ---------------------------------------------------------------------------


@mcp.tool
async def list_gateways(
    limit: int = 100,
    offset: int = 0,
    organization_id: str | None = None,
) -> Any:
    """List LoRaWAN gateways. Returns ``{totalCount, localNS, result:[...]}``."""
    return await _get_client().get(
        "/api/gateways",
        params={
            "limit": limit,
            "offset": offset,
            "organizationID": _org(organization_id),
        },
    )


@mcp.tool
async def list_packets(organization_id: str | None = None) -> Any:
    """List recent LoRaWAN packets (frame log). Returns ``{packets:[...]}``."""
    return await _get_client().get(
        "/api/urpackets",
        params={"organizationID": _org(organization_id)},
    )


@mcp.tool
async def delete_packets(organization_id: str | None = None) -> Any:
    """Clear the packet/frame log."""
    return await _get_client().delete(
        "/api/urpackets",
        params={"organizationID": _org(organization_id)},
    )


@mcp.tool
async def list_payload_codecs() -> Any:
    """List available payload codecs (short form). Returns
    ``{totalCount, result:[{id, name}]}``."""
    return await _get_client().get("/api/payloadcodecs-short")


@mcp.tool
async def get_network_server_settings() -> Any:
    """Get the embedded network server settings."""
    return await _get_client().get("/api/network-server/settings")


@mcp.tool
async def get_packet_forwarder_network_servers() -> Any:
    """Get configured packet-forwarder network servers."""
    return await _get_client().get("/api/packet-forwarder/network-servers")


def main() -> None:
    """Console-script entry point: run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
