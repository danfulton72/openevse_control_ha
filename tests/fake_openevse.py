"""Fake OpenEVSE WiFi modules for end-to-end tests."""

from __future__ import annotations

import base64
import json
from typing import Any

from aiohttp import web

MANUAL = 65537


class FakeOpenEVSE:
    """In-memory charger implementing the APIs used by the integration."""

    def __init__(
        self,
        password: str | None = None,
        username: str = "admin",
        *,
        legacy: bool = False,
    ) -> None:
        self.password = password
        self.username = username
        self.legacy = legacy
        self.junk = False
        self.config: dict[str, Any] = {
            "hostname": "openevse-7f3a",
            "version": "4.0.0" if legacy else "5.1.5",
            "firmware": "7.1.3" if legacy else "8.2.2.EU",
            "buildenv": "openevse_wifi_v1",
            "mqtt_announce_topic": "openevse/announce/7f3a",
        }
        if legacy:
            self.config["pause_uses_disabled"] = False
        else:
            self.config.update(
                {
                    "max_current_soft": 12,
                    "max_current_hard": 32,
                    "min_current_hard": 6,
                    "rfid_enabled": False,
                }
            )

        self.status: dict[str, Any] = {
            "state": 3,
            "pilot": 12,
            "divertmode": 1,
            "macaddress": "AA:BB:CC:7F:3A:12",
            "ipaddress": "192.0.2.10",
        }
        if not legacy:
            self.status.update(
                {
                    "status": "active",
                    "max_current": 12,
                    "config_version": 1,
                    "claims_version": 1,
                    "override_version": 1,
                }
            )

        self.legacy_min_current = 6
        self.legacy_max_current = 32
        self.manual: dict[str, Any] | None = None
        self.other_claims: list[dict[str, Any]] = []
        self.log: list[tuple[str, str, Any]] = []
        self.rapi_log: list[str] = []
        self.override_delete_failure: str | None = None

        self.app = web.Application()
        self.app.router.add_route("GET", "/status", self._status)
        self.app.router.add_route("GET", "/config", self._config)
        if legacy:
            self.app.router.add_route("GET", "/r", self._rapi)
        else:
            self.app.router.add_route("*", "/override", self._override)
            self.app.router.add_route("GET", "/claims/target", self._target)
            self.app.router.add_route("GET", "/claims", self._claims)

    def bump(self) -> None:
        """Bump claim and override versions after an external/manual change."""
        if not self.legacy:
            self.status["claims_version"] += 1
            self.status["override_version"] += 1

    def bump_config(self) -> None:
        """Bump the modern configuration version."""
        if not self.legacy:
            self.status["config_version"] += 1

    def _all_claims(self) -> list[dict[str, Any]]:
        claims = list(self.other_claims)
        if self.manual is not None:
            claims.append({"client": MANUAL, "priority": 1000, **self.manual})
        return sorted(claims, key=lambda claim: claim["priority"], reverse=True)

    def _authorised(self, request: web.Request) -> bool:
        if not self.password:
            return True
        header = request.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            user, _, pwd = base64.b64decode(header[6:]).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            return False
        return user == self.username and pwd == self.password

    async def _pre(self, request: web.Request) -> web.Response | None:
        body = None
        if request.can_read_body and request.content_length:
            body = json.loads(await request.text())
        request["body"] = body
        self.log.append((request.method, request.path, body))
        if not self._authorised(request):
            return web.json_response({"msg": "auth"}, status=401)
        return None

    async def _status(self, request: web.Request) -> web.Response:
        return await self._pre(request) or web.json_response(self.status)

    async def _config(self, request: web.Request) -> web.Response:
        if resp := await self._pre(request):
            return resp
        return web.json_response({"foo": 1} if self.junk else self.config)

    async def _claims(self, request: web.Request) -> web.Response:
        return await self._pre(request) or web.json_response(self._all_claims())

    async def _target(self, request: web.Request) -> web.Response:
        if resp := await self._pre(request):
            return resp
        props: dict[str, Any] = {"state": "active"}
        owners: dict[str, int] = {}
        for prop in ("state", "charge_current", "max_current"):
            for claim in self._all_claims():
                if prop in claim:
                    props[prop] = claim[prop]
                    owners[prop] = claim["client"]
                    break
        props.setdefault("charge_current", self.config["max_current_soft"])
        return web.json_response({"properties": props, "claims": owners})

    async def _override(self, request: web.Request) -> web.Response:
        if resp := await self._pre(request):
            return resp
        if request.method == "GET":
            return web.json_response(self.manual or {})
        if request.method == "POST":
            body = request["body"] or {}
            props = {
                key: value
                for key, value in body.items()
                if key in ("state", "charge_current", "max_current")
            }
            props["auto_release"] = bool(body.get("auto_release", True))
            self.manual = props
            self.bump()
            return web.json_response({"msg": "Created"}, status=201)
        if request.method == "DELETE":
            if self.override_delete_failure is not None:
                return web.json_response(
                    {"msg": self.override_delete_failure}, status=500
                )
            if self.manual is None:
                return web.json_response(
                    {"msg": "Failed to release manual override"}, status=500
                )
            self.manual = None
            self.bump()
            return web.json_response({"msg": "Deleted"})
        return web.json_response({"msg": "Method not allowed"}, status=405)

    async def _rapi(self, request: web.Request) -> web.Response:
        if resp := await self._pre(request):
            return resp
        if request.query.get("json") != "1":
            return web.Response(text="json=1 required", status=400)
        command = request.query.get("rapi", "").strip()
        self.rapi_log.append(command)

        if command == "$GC":
            response = f"$OK {self.legacy_min_current} {self.legacy_max_current}"
        elif command == "$FE":
            self.status["state"] = 2
            response = "$OK"
        elif command == "$FS":
            self.status["state"] = 254
            response = "$OK"
        elif command == "$FD":
            self.status["state"] = 255
            response = "$OK"
        elif command.startswith("$SC "):
            try:
                amps = int(command.split(maxsplit=1)[1])
            except ValueError:
                response = "$NK"
            else:
                if not self.legacy_min_current <= amps <= self.legacy_max_current:
                    response = "$NK"
                else:
                    self.status["pilot"] = amps
                    response = "$OK"
        else:
            response = "$NK"
        return web.json_response({"cmd": command, "ret": response})

    def writes(self) -> list[tuple[str, Any]]:
        """Return state-changing modern override requests."""
        return [
            (method, body)
            for method, path, body in self.log
            if method in ("POST", "DELETE") and path == "/override"
        ]

    def rapi_writes(self) -> list[str]:
        """Return state-changing legacy RAPI commands."""
        return [command for command in self.rapi_log if command != "$GC"]
