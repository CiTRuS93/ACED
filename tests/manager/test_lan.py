"""Opt-in network origins retain the existing local manager authority boundary."""

import httpx
import pytest

from aced import Principal
from aced.manager import create_manager_app
from tests.test_runtime import compose

LAN = "http://192.168.31.88:8767"
TOKEN = "lan-fixture-bootstrap-token-at-least-32-characters"


async def test_lan_origin_requires_explicit_opt_in():
    runtime, *_ = compose()
    try:
        for options in ({}, {"allow_lan": False}):
            with pytest.raises(ValueError, match="allow_lan=True"):
                create_manager_app(runtime, origin=LAN, **options)
        app = create_manager_app(runtime)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=LAN
        ) as client:
            assert (await client.get("/")).status_code == 403
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "origin",
    [
        "http://0.0.0.0:8767",
        "http://[::]:8767",
        "http://*:8767",
        "http://*.example.test:8767",
        "http://:8767",
        "http://user@192.168.31.88:8767",
        "http://@192.168.31.88:8767",
        LAN + "/path",
        LAN + "/",
        LAN + "?query=1",
        LAN + "#fragment",
        LAN + "\n",
        "http://192.168.31.88:invalid",
        "http://192.168.31.88:65536",
        "http://192.168.31.88:0",
    ],
)
async def test_lan_requires_one_concrete_origin(origin):
    runtime, *_ = compose()
    try:
        with pytest.raises(ValueError):
            create_manager_app(runtime, origin=origin, allow_lan=True)
    finally:
        await runtime.close()


async def test_lan_session_csrf_and_runtime_authority():
    runtime, _, runner, _, identity = compose()
    try:
        app = create_manager_app(runtime, origin=LAN, allow_lan=True, bootstrap_token=TOKEN)
        # Factory and HTTP reads must not start a worker or mutate runtime state.
        assert await runtime.list_runs("demo") == ()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=LAN
        ) as client:
            assert (await client.get("/")).status_code == 200
            assert (await client.get("/api/context")).status_code == 401
            headers = {"Origin": LAN}
            assert (
                await client.post("/api/session", json={"token": "wrong" * 8}, headers=headers)
            ).status_code == 401
            response = await client.post("/api/session", json={"token": TOKEN}, headers=headers)
            assert response.status_code == 200
            assert "HttpOnly" in response.headers["set-cookie"]
            assert "SameSite=strict" in response.headers["set-cookie"]
            assert (
                await client.post("/api/session", json={"token": TOKEN}, headers=headers)
            ).status_code == 401
            assert (await client.get("/api/context")).json()["projects"][0]["id"] == "demo"
            body = {"project_id": "demo", "objective": "LAN fixture", "key": "lan-fixture"}
            assert (await client.post("/api/runs", json=body, headers=headers)).status_code == 403
            headers["X-ACED-CSRF"] = "wrong"
            assert (await client.post("/api/runs", json=body, headers=headers)).status_code == 403
            headers["X-ACED-CSRF"] = response.json()["csrf"]
            assert (await client.post("/api/runs", json=body, headers=headers)).status_code == 200
            assert runner.starts == []
            identity.principal = Principal("revoked", frozenset())
            assert (await client.get("/api/runs?project_id=demo")).status_code == 403
            assert (await client.post("/api/runs", json=body, headers=headers)).status_code == 403
            client.cookies.clear()
            assert (await client.get("/api/context")).status_code == 401
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "unexpected",
    [
        {"Host": "192.168.31.89:8767"},
        {"Host": "192.168.31.88:8765"},
        {"Host": "127.0.0.1:8767"},
        {"Host": "evil.test"},
        {"Origin": "http://192.168.31.89:8767"},
        {"Origin": "http://192.168.31.88:8765"},
        {"Origin": "https://192.168.31.88:8767"},
        {"Origin": "http://localhost:8767"},
        {"Origin": "null"},
    ],
)
async def test_lan_rejects_unexpected_host_or_origin_before_and_after_login(unexpected):
    runtime, *_ = compose()
    try:
        app = create_manager_app(runtime, origin=LAN, allow_lan=True, bootstrap_token=TOKEN)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=LAN
        ) as client:
            assert (
                await client.post(
                    "/api/session", json={"token": TOKEN}, headers={"Origin": LAN, **unexpected}
                )
            ).status_code == 403
            response = await client.post(
                "/api/session", json={"token": TOKEN}, headers={"Origin": LAN}
            )
            assert response.status_code == 200
            assert (await client.get("/api/context", headers=unexpected)).status_code == 403
            assert (
                await client.post(
                    "/api/runs",
                    json={"project_id": "demo", "objective": "Never created", "key": "blocked"},
                    headers={"Origin": LAN, "X-ACED-CSRF": response.json()["csrf"], **unexpected},
                )
            ).status_code == 403
            assert (
                await client.post(
                    "/api/runs", json={}, headers={"X-ACED-CSRF": response.json()["csrf"]}
                )
            ).status_code == 403  # Missing Origin stays forbidden even with a valid session.
            assert await runtime.list_runs("demo") == ()
    finally:
        await runtime.close()
