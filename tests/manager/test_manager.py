"""HTTP authority and fixture journeys; no credentials or real exposure."""

import asyncio
from contextlib import aclosing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from aced import AuthorizationError, Goal, Principal
from aced.manager import create_manager_app
from aced.manager.contracts import MetricPoint, MetricSeries
from aced.manager.demo import ConsoleFixture, create_demo_app
from aced.reference import DemoClock
from tests.test_runtime import compose, drive

ORIGIN = "http://127.0.0.1:8765"
TOKEN = "test-bootstrap-token-at-least-32-characters"


async def client_for(runtime, **options):
    app = create_manager_app(runtime, bootstrap_token=TOKEN, **options)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)
    response = await client.post("/api/session", json={"token": TOKEN}, headers={"Origin": ORIGIN})
    assert response.status_code == 200
    client.headers.update({"Origin": ORIGIN, "X-ACED-CSRF": response.json()["csrf"]})
    return client, app


async def test_discovery_cursor_authority_redaction_and_reopen(tmp_path):
    runtime, clock, _, _, identity = compose(tmp_path / "manager.sqlite")
    first = await runtime.start(Goal("demo", "First"), key="first")
    await drive(runtime, clock, first.id)
    second = await runtime.start(Goal("demo", "Second"), key="second")
    page = await runtime.list_runs("demo", limit=1)
    assert page[0][1].id == first.id
    assert (await runtime.list_runs("demo", after=page[0][0]))[0][1].id == second.id
    with pytest.raises(ValueError):
        await runtime.list_runs("demo", limit=0)
    row = await runtime.store.get(second.id)
    await runtime.store.save(
        row, {**row.data, "read_claims": ["secret:read"]}, "restricted", "host", clock.now()
    )
    assert (await runtime.list_runs("demo"))[1][1].redacted
    identity.principal = Principal("outsider", frozenset({"run:inspect", "project:other"}))
    with pytest.raises(AuthorizationError):
        await runtime.list_runs("demo")
    await runtime.close()
    reopened, *_ = compose(tmp_path / "manager.sqlite")
    assert len(await reopened.list_runs("demo")) == 2
    assert await reopened.store.verify_audit()
    await reopened.close()


async def test_session_origin_csrf_and_revoked_identity(monkeypatch):
    runtime, _, _, _, identity = compose()
    app = create_manager_app(runtime, bootstrap_token=TOKEN, session_seconds=1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (await client.get("/api/context")).status_code == 401
        assert (await client.get("/api/context", headers={"Host": "evil.test"})).status_code == 403
        assert (await client.post("/api/session", json={"token": TOKEN})).status_code == 403
        assert (
            await client.post(
                "/api/session", json={"token": TOKEN}, headers={"Origin": "http://evil.test"}
            )
        ).status_code == 403
        headers = {"Origin": ORIGIN}
        assert (
            await client.post("/api/session", json={"token": "x" * 32}, headers=headers)
        ).status_code == 401
        assert (
            await client.post("/api/session", json={"token": "é" * 32}, headers=headers)
        ).status_code == 401
        response = await client.post("/api/session", json={"token": TOKEN}, headers=headers)
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert (
            await client.post("/api/session", json={"token": TOKEN}, headers=headers)
        ).status_code == 401
        assert (await client.get("/api/context")).json()["csrf"] == response.json()["csrf"]
        assert (await client.post("/api/runs", json={}, headers=headers)).status_code == 403
        headers["X-ACED-CSRF"] = response.json()["csrf"]
        assert (await client.post("/api/runs", json={}, headers=headers)).status_code == 422
        identity.principal = Principal("revoked", frozenset())
        assert (await client.get("/api/context")).json()["projects"] == []
        assert (await client.get("/api/runs?project_id=demo")).status_code == 403
        monkeypatch.setattr("aced.manager.app.time.monotonic", lambda: 10**20)
        assert (await client.get("/api/context")).status_code == 401
    await runtime.close()


@pytest.mark.parametrize(
    "options",
    [
        {"origin": "https://example.com"},
        {"origin": "http://localhost/path"},
        {"origin": "http://user@localhost"},
        {"session_seconds": 0},
        {"bootstrap_token": "short"},
    ],
)
async def test_invalid_local_configuration(options):
    runtime, *_ = compose()
    with pytest.raises(ValueError):
        create_manager_app(runtime, **options)
    await runtime.close()


async def test_bootstrap_expiration(monkeypatch):
    runtime, *_ = compose()
    app = create_manager_app(runtime, bootstrap_token=TOKEN)
    monkeypatch.setattr("aced.manager.app.time.monotonic", lambda: 10**20)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (
            await client.post("/api/session", json={"token": TOKEN}, headers={"Origin": ORIGIN})
        ).status_code == 401
    await runtime.close()


async def test_legacy_csrf_header_keeps_existing_clients_compatible():
    runtime, *_ = compose()
    client, _ = await client_for(runtime)
    try:
        async with aclosing(client):
            token = client.headers.pop("X-ACED-CSRF")
            client.headers["X-CDDAI-CSRF"] = token
            body = {"project_id": "demo", "objective": "Existing host", "key": "legacy"}
            assert (await client.post("/api/runs", json=body)).status_code == 200
            client.headers["X-ACED-CSRF"] = "wrong"
            assert (await client.post("/api/runs", json=body)).status_code == 403
            del client.headers["X-ACED-CSRF"]
            client.headers["X-CDDAI-CSRF"] = "wrong"
            assert (await client.post("/api/runs", json=body)).status_code == 403
    finally:
        await runtime.close()


async def test_controls_idempotency_history_and_unavailable_adapters():
    runtime, clock, _, _, _ = compose()
    client, _ = await client_for(runtime)
    async with aclosing(client):
        body = {"project_id": "demo", "objective": "Learn", "key": "stable"}
        response = await client.post("/api/runs", json=body)
        assert response.status_code == 200
        run_id = response.json()["id"]
        assert (await client.post("/api/runs", json=body)).json()["id"] == run_id
        assert (await client.post("/api/runs", json={**body, "key": "other"})).status_code == 409
        assert (
            await client.post("/api/runs", json={**body, "project_id": "missing"})
        ).status_code == 404
        assert len((await client.get("/api/runs?project_id=demo&limit=1")).json()["items"]) == 1
        prefix = f"/api/runs/{run_id}"
        assert (await client.post(prefix + "/actions/hold", json={})).json()["status"] == "held"
        assert (await client.post(prefix + "/actions/resume", json={})).json()["status"] == "active"
        assert (await client.post(prefix + "/actions/repropose", json={})).status_code == 422
        assert (await client.get(prefix + "/history?limit=1")).json()["next"] is not None
        assert (await client.get(prefix + "/tasks")).json()["items"] == []
        assert (await client.get(f"/api/approvals/{run_id}")).status_code == 501
        assert (
            await client.post(
                f"/api/approvals/{run_id}/none",
                json={"task_fingerprint": "f", "decision": "approve", "key": "k"},
            )
        ).status_code == 501
        query = f"/api/experiments/{run_id}?cycle=1&experiment_id={run_id}:1:experiment"
        assert (await client.get(query)).status_code == 501
        stopped = await client.post(prefix + "/actions/stop", json={})
        assert stopped.status_code == 200
        assert stopped.json()["status"] in {"stopping", "stopped"}
        assert (await client.get("/api/runs/absent")).status_code == 404
        assert (await client.get(prefix)).status_code == 200
        assert (await client.get(prefix + "/history?after=-1")).status_code == 422
    await runtime.close()


async def test_redaction_does_not_leak_host_adapters():
    runtime, clock, _, infra, _ = compose()
    view = await runtime.start(Goal("demo", "Private"), key="private")
    row = await runtime.store.get(view.id)
    await runtime.store.save(
        row, {**row.data, "read_claims": ["private"]}, "restrict", "host", clock.now()
    )
    client, _ = await client_for(runtime)
    async with aclosing(client):
        assert (await client.get(f"/api/runs/{view.id}")).json()["data"] == {}
        for suffix in (
            f"runs/{view.id}/history",
            f"runs/{view.id}/tasks",
            f"approvals/{view.id}",
            f"experiments/{view.id}?cycle=1&experiment_id=x",
        ):
            assert (await client.get("/api/" + suffix)).status_code == 403
    await runtime.close()


async def fixture_client():
    clock = DemoClock(datetime.now(UTC))
    infra = ConsoleFixture(clock)
    runtime, _, runner, _, identity = compose(clock=clock, infra=infra)
    client, app = await client_for(runtime, approvals=infra, metrics=infra)
    run = await runtime.start(Goal("demo", "Fixture journey"), key="fixture")
    return client, runtime, clock, infra, run, app


async def test_approval_fingerprints_reproposal_and_uncertain_reply():
    client, runtime, clock, infra, run, _ = await fixture_client()
    async with aclosing(client):
        await runtime.advance(run.id)
        requests = (await client.get(f"/api/approvals/{run.id}")).json()["items"]
        assert len(requests) == 1
        request = requests[0]
        path = f"/api/approvals/{run.id}/{request['id']}"
        body = {
            "task_fingerprint": request["task_fingerprint"],
            "decision": "approve",
            "key": "decision-1",
        }
        assert (
            await client.post(path, json={**body, "task_fingerprint": "forged"})
        ).status_code == 422
        assert (await client.post(path, json={**body, "subject": "admin"})).status_code == 422
        assert (await client.post(path, json=body)).json()["status"] == "approved"
        assert (await client.post(path, json=body)).json()["status"] == "approved"
        assert (await client.post(path, json={**body, "decision": "deny"})).status_code == 409
        await runtime.repropose(run.id)
        assert (await client.post(path, json={**body, "key": "new"})).status_code == 409
        assert (await client.get(f"/api/approvals/{run.id}")).json()["items"] == []
        await runtime.advance(run.id)
        current = (await client.get(f"/api/approvals/{run.id}")).json()["items"][0]
        assert current["task_fingerprint"] != request["task_fingerprint"]
        clock.tick(3601)
        assert (
            await client.post(
                f"/api/approvals/{run.id}/{current['id']}",
                json={**body, "task_fingerprint": current["task_fingerprint"], "key": "expired"},
            )
        ).status_code == 409
    await runtime.close()


async def test_complete_fixture_cycles_metrics_and_continuation():
    client, runtime, clock, infra, run, _ = await fixture_client()
    seen = set()
    async with aclosing(client):
        for _ in range(150):
            view = await runtime.inspect(run.id)
            if view.status == "completed":
                break
            await runtime.advance(run.id)
            view = await runtime.inspect(run.id)
            for request in await infra.list_requests(
                view, Principal("host", frozenset({"run:*", "project:*"}))
            ):
                if request.status == "pending":
                    response = await client.post(
                        f"/api/approvals/{run.id}/{request.id}",
                        json={
                            "task_fingerprint": request.task_fingerprint,
                            "decision": "approve",
                            "key": request.id,
                        },
                    )
                    assert response.status_code == 200
            for phase, suffix in (("canary", "canary"), ("main", "experiment")):
                query = {
                    "cycle": 1,
                    "phase": phase,
                    "experiment_id": f"{run.id}:1:{suffix}",
                    "end": (clock.now() + timedelta(seconds=1)).isoformat(),
                }
                response = await client.get(f"/api/experiments/{run.id}", params=query)
                assert response.status_code == 200, response.text
                result = response.json()
                seen.add((phase, result["exposure"]))
                assert all(len(series["points"]) <= 240 for series in result["series"])
            clock.tick(1)
        else:
            pytest.fail(str(view.blocker))
        assert {
            ("canary", "active"),
            ("canary", "zero"),
            ("main", "active"),
            ("main", "zero"),
        } <= seen
        assert view.data["retained_source"] == "source-0"
        response = await client.post(
            "/api/runs",
            json={
                "project_id": "demo",
                "objective": "Next goal",
                "key": "next",
                "continuation": {
                    "previous_run_id": run.id,
                    "accepted_source": "source-0",
                    "learning_references": [view.data["learning"][0]["reference"]],
                    "candidate_ids": ["candidate-a"],
                },
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["learning"]
    await runtime.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"experiment_id": "wrong"},
        {"cycle": 2},
        {"start": "2000-01-01T00:00:00Z"},
        {"start": "2099-01-01T00:00:00Z"},
        {"end": "2026-01-01"},
        {"max_points": 1001},
    ],
)
async def test_metric_query_scope_and_bounds(changes):
    client, runtime, _, _, run, _ = await fixture_client()
    async with aclosing(client):
        query = {"cycle": 1, "experiment_id": f"{run.id}:1:experiment", **changes}
        assert (await client.get(f"/api/experiments/{run.id}", params=query)).status_code == 422
    await runtime.close()


@pytest.mark.parametrize(
    "fault", ["identity", "freshness", "count", "window", "timeout", "private_error", "unexpected"]
)
async def test_host_metric_errors_are_bounded_and_redacted(fault):
    client, runtime, clock, infra, run, _ = await fixture_client()
    original = infra.read

    async def broken(*args, **kwargs):
        if fault == "timeout":
            raise TimeoutError("secret-host-token")
        if fault == "unexpected":
            raise RuntimeError("secret-host-token")
        if fault == "private_error":
            raise OSError("secret-host-token")
        snapshot = await original(*args, **kwargs)
        if fault == "identity":
            snapshot.run_id = "other"
        if fault == "freshness":
            snapshot.fresh_until = clock.now() - timedelta(seconds=1)
        if fault in {"count", "window"}:
            snapshot.series = [
                MetricSeries(
                    name="bad",
                    unit="%",
                    points=[
                        MetricPoint(
                            at=clock.now() + timedelta(days=100)
                            if fault == "window"
                            else clock.now(),
                            value=1,
                        )
                    ]
                    * (3 if fault == "count" else 1),
                )
            ]
        return snapshot

    infra.read = broken
    async with aclosing(client):
        response = await client.get(
            f"/api/experiments/{run.id}",
            params={"cycle": 1, "experiment_id": f"{run.id}:1:experiment", "max_points": 2},
        )
        assert response.status_code in {422, 503}
        assert "secret-host-token" not in response.text
    await runtime.close()


async def test_demo_lifespan_and_assets():
    app = create_demo_app(bootstrap_token=TOKEN)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=ORIGIN
        ) as client:
            response = await client.get("/")
            assert response.status_code == 200
            assert "Cycle manager" in response.text
            assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
            await asyncio.sleep(0.3)
            assert len(await app.state.runtime.list_runs("demo")) == 1


async def test_static_missing_assets(monkeypatch):
    runtime, *_ = compose()
    client, _ = await client_for(runtime)
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    async with aclosing(client):
        assert (await client.get("/")).status_code == 503
    await runtime.close()
