"""Live integration smoke test against a real Milesight gateway.

Reads connection settings from the environment (or a local .env) and exercises
the read-only endpoints. It does NOT create, modify or delete anything.

Run:
    uv run python test_live.py
"""

from __future__ import annotations

import asyncio
import os

from milesight_mcp.client import MilesightClient, encrypt_password


def _load_dotenv() -> None:
    """Minimal .env loader so the test runs without extra deps."""
    path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


async def main() -> int:
    _load_dotenv()
    host = os.environ.get("MILESIGHT_HOST", "192.168.1.1")
    user = os.environ.get("MILESIGHT_USER", "admin")
    password = os.environ.get("MILESIGHT_PASSWORD", "")
    org = os.environ.get("MILESIGHT_ORG_ID", "1")

    # Sanity check the AES routine against the documented vector shape.
    print(f"encrypt('test') = {encrypt_password('test')}")

    client = MilesightClient(host, user, password)
    try:
        jwt = await client.login()
        print(f"[ok] login -> jwt len {len(jwt)}")

        apps = await client.get(
            "/api/urapplications", params={"limit": 100, "organizationID": org}
        )
        print(f"[ok] applications: {apps.get('totalCount')}")

        devices = await client.get(
            "/api/urdevices", params={"limit": 100, "organizationID": org}
        )
        print(f"[ok] devices: {devices.get('devTotalCount')}")

        profiles = await client.get(
            "/api/urprofiles", params={"limit": 100, "organizationID": org}
        )
        print(f"[ok] profiles: {profiles.get('totalCount')}")

        gateways = await client.get(
            "/api/gateways", params={"limit": 100, "organizationID": org}
        )
        print(
            f"[ok] gateways: {gateways.get('totalCount')} "
            f"(localNS={gateways.get('localNS')})"
        )

        mcg = await client.get(
            "/api/multicast-groups",
            params={"limit": 100, "organizationID": org},
        )
        print(f"[ok] multicast groups: {mcg.get('totalCount')}")

        codecs = await client.get("/api/payloadcodecs-short")
        print(f"[ok] payload codecs: {codecs.get('totalCount')}")

        print("\nALL LIVE CHECKS PASSED")
        return 0
    except Exception as exc:  # noqa: BLE001 - smoke test reports any failure
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        return 1
    finally:
        await client.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
