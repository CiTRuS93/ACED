"""Same-origin local console. Host owns the runtime, worker and operator identity."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, TypeVar
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, Field

from aced._json import json_value
from aced.models import AuthorizationError, Goal, Inspection, Principal, RunContinuation, authorize
from aced.runtime import Runtime
from aced.store import ConflictError, NotFoundError, StoreError

from .contracts import ApprovalAdapter, ApprovalDecision, MetricsAdapter, Model

_T = TypeVar("_T")


class Bootstrap(Model):
    token: str = Field(min_length=32, max_length=256)


class Continuation(Model):
    previous_run_id: str
    accepted_source: str
    learning_references: list[str] = Field(default_factory=list, max_length=32)
    candidate_ids: list[str] = Field(default_factory=list, max_length=32)


class Start(Model):
    project_id: str = Field(min_length=1, max_length=256)
    objective: str = Field(min_length=1, max_length=10000)
    key: str = Field(min_length=1, max_length=128)
    continuation: Continuation | None = None


def create_manager_app(
    runtime: Runtime,
    *,
    origin: str = "http://127.0.0.1:8765",
    allow_lan: bool = False,
    bootstrap_token: str | None = None,
    project_labels: Mapping[str, str] | None = None,
    approvals: ApprovalAdapter | None = None,
    metrics: MetricsAdapter | None = None,
    demo: bool = False,
    session_seconds: int = 3600,
) -> FastAPI:
    """Use runtime's fixed host-authenticated operator context; never swap contexts.

    Loopback is the default; ``allow_lan=True`` permits an explicit non-loopback
    HTTP ``origin``. The host configures its ASGI server's bind address separately
    and starts/joins its existing worker. No socket or worker is started here.
    ``app.state.bootstrap_token`` is delivered out of band, expires after five minutes,
    and can be exchanged once. Restart the app for a new operator session.
    """
    parsed = urlsplit(origin)
    if (
        type(allow_lan) is not bool
        or parsed.scheme != "http"
        or not parsed.hostname
        or parsed.hostname in {"0.0.0.0", "::"}
        or "*" in parsed.netloc
        or any(character.isspace() for character in origin)
        or origin != f"http://{parsed.netloc}"
        or parsed.username is not None
        or parsed.port == 0
        or session_seconds <= 0
    ):
        raise ValueError("manager requires an explicit HTTP origin and positive session lifetime")
    if not allow_lan and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("non-loopback manager origins require allow_lan=True")
    token = bootstrap_token or secrets.token_urlsafe(32)
    if len(token) < 32:
        raise ValueError("bootstrap token must contain at least 32 characters")
    bootstrap_deadline = time.monotonic() + 300
    session = ""
    csrf = ""
    session_deadline = 0.0
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.bootstrap_token = token
    labels = dict(project_labels or {})

    async def host_call(work: Awaitable[_T]) -> _T:
        try:
            return await asyncio.wait_for(work, timeout=runtime.host_timeout_seconds)
        except (AuthorizationError, ValueError, StoreError, OSError):
            raise
        except Exception as error:
            raise OSError("Host call failed") from error

    async def principal(project: str, action: str = "run:inspect") -> Principal:
        who = await host_call(runtime.identity.authenticate(runtime.auth_context))
        authorize(who, action, project)
        return who

    async def readable(run_id: str) -> tuple[Inspection, Principal]:
        view = await runtime.inspect(run_id)
        who = await principal(view.project_id)
        if view.redacted or not set(view.data.get("read_claims", ())).issubset(who.claims):
            raise AuthorizationError("restricted evidence")
        return view, who

    @app.middleware("http")
    async def local_session(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.headers.get("host") != parsed.netloc:
            return JSONResponse({"detail": "Invalid host"}, status_code=403)
        supplied_origin = request.headers.get("origin")
        if supplied_origin is not None and supplied_origin != origin:
            return JSONResponse({"detail": "Invalid origin"}, status_code=403)
        mutation = request.method not in {"GET", "HEAD"}
        if mutation and supplied_origin != origin:
            return JSONResponse({"detail": "Same-origin request required"}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path != "/api/session":
            if (
                not session
                or time.monotonic() >= session_deadline
                or not secrets.compare_digest(request.cookies.get("cddai_session", ""), session)
            ):
                return JSONResponse({"detail": "Local session expired or missing"}, status_code=401)
            if mutation and not secrets.compare_digest(
                request.headers.get("x-aced-csrf", request.headers.get("x-cddai-csrf", "")), csrf
            ):
                return JSONResponse({"detail": "Invalid CSRF token"}, status_code=403)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self'; "
                    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                    "connect-src 'self'; frame-ancestors 'none'; "
                    "base-uri 'none'; form-action 'self'"
                ),
            }
        )
        return response

    async def failure(request: Request, error: Exception) -> JSONResponse:
        # Never echo host exceptions, credentials, or validation inputs.
        status = 503
        detail = "Host unavailable; refresh to reconcile the recorded outcome."
        if isinstance(error, AuthorizationError):
            status, detail = 403, "Operation or evidence access denied."
        elif isinstance(error, NotFoundError):
            status, detail = 404, "Run not found."
        elif isinstance(error, ConflictError):
            status, detail = 409, "State changed or project already owned; refresh before acting."
        elif isinstance(error, (ValueError, RequestValidationError)):
            status, detail = 422, "Request is not valid for the current state."
        return JSONResponse({"detail": detail}, status_code=status)

    for error_type in (
        AuthorizationError,
        NotFoundError,
        ConflictError,
        StoreError,
        ValueError,
        TimeoutError,
        OSError,
    ):
        app.add_exception_handler(error_type, failure)

    app.add_exception_handler(RequestValidationError, failure)

    @app.post("/api/session")
    async def exchange(body: Bootstrap) -> Response:
        nonlocal token, session, csrf, session_deadline
        if (
            not token
            or time.monotonic() >= bootstrap_deadline
            or not secrets.compare_digest(body.token.encode(), token.encode())
        ):
            raise HTTPException(401, "Bootstrap token expired or already used")
        # Consume before yielding so concurrent exchanges cannot both succeed.
        token = ""
        await host_call(runtime.identity.authenticate(runtime.auth_context))
        app.state.bootstrap_token = None
        session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        session_deadline = time.monotonic() + session_seconds
        response = JSONResponse({"csrf": csrf})
        response.set_cookie(
            "cddai_session", session, httponly=True, samesite="strict", max_age=session_seconds
        )
        return response

    @app.get("/api/context")
    async def context() -> dict[str, Any]:
        who = await host_call(runtime.identity.authenticate(runtime.auth_context))
        projects = []
        for project in runtime.projects.values():
            try:
                authorize(who, "run:inspect", project.project_id)
            except AuthorizationError:
                continue
            projects.append(
                {
                    "id": project.project_id,
                    "label": labels.get(project.project_id, project.project_id),
                }
            )
        return {
            "csrf": csrf,
            "projects": projects,
            "demo": demo,
            "approvals": approvals is not None,
            "metrics": metrics is not None,
        }

    @app.get("/api/runs")
    async def runs(
        project_id: str, after: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
    ) -> dict[str, Any]:
        page = await runtime.list_runs(project_id, after=after, limit=limit)
        return {
            "items": [{"seq": seq, "run": json_value(view)} for seq, view in page],
            "next": page[-1][0] if len(page) == limit else None,
        }

    @app.post("/api/runs")
    async def start(body: Start) -> Any:
        if body.project_id not in runtime.projects:
            raise HTTPException(404, "Project not configured")
        continuation = (
            RunContinuation(**body.continuation.model_dump()) if body.continuation else None
        )
        return json_value(
            await runtime.start(
                Goal(body.project_id, body.objective), key=body.key, continuation=continuation
            )
        )

    @app.get("/api/runs/{run_id}")
    async def inspect(run_id: str) -> Any:
        return json_value(await runtime.inspect(run_id))

    @app.get("/api/runs/{run_id}/{collection}")
    async def records(
        run_id: str,
        collection: Literal["history", "tasks"],
        after: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
    ) -> Any:
        method = runtime.history if collection == "history" else runtime.tasks
        items = await method(run_id, after=after, limit=limit)
        return {
            "items": json_value(items),
            "next": items[-1]["seq"] if len(items) == limit else None,
        }

    @app.post("/api/runs/{run_id}/actions/{action}")
    async def control(run_id: str, action: Literal["hold", "resume", "stop", "repropose"]) -> Any:
        method = {
            "hold": runtime.hold,
            "resume": runtime.resume,
            "stop": runtime.stop,
            "repropose": runtime.repropose,
        }[action]
        return json_value(await method(run_id))

    @app.get("/api/approvals/{run_id}")
    async def inbox(run_id: str) -> Any:
        view, who = await readable(run_id)
        if approvals is None:
            raise HTTPException(501, "Host approval connection unavailable")
        items = await host_call(approvals.list_requests(view, who))
        if len(items) > 100 or any(item.run_id != run_id for item in items):
            raise ValueError("host approval scope mismatch")
        return {"items": [item.model_dump(mode="json") for item in items]}

    @app.post("/api/approvals/{run_id}/{request_id}")
    async def decide(run_id: str, request_id: str, body: ApprovalDecision) -> Any:
        view, who = await readable(run_id)
        if approvals is None:
            raise HTTPException(501, "Host approval connection unavailable")
        result = await host_call(approvals.decide(view, request_id, body, who))
        if (
            result.run_id != run_id
            or result.id != request_id
            or result.task_fingerprint != body.task_fingerprint
        ):
            raise ValueError("host decision scope mismatch")
        return result.model_dump(mode="json")

    @app.get("/api/experiments/{run_id}")
    async def experiment(
        run_id: str,
        cycle: int = Query(ge=1),
        phase: Literal["canary", "main"] = "main",
        experiment_id: str = Query(min_length=1, max_length=512),
        start: AwareDatetime | None = None,
        end: AwareDatetime | None = None,
        max_points: int = Query(240, ge=2, le=1000),
    ) -> Any:
        view, who = await readable(run_id)
        if metrics is None:
            raise HTTPException(501, "Host metrics connection unavailable")
        end = end or datetime.now(UTC)
        start = start or end - timedelta(hours=1)
        if not timedelta(0) < end - start <= timedelta(days=31):
            raise ValueError("metric window must be positive and at most 31 days")
        # Historical identities are host-verified; current identities are also checked here.
        identity = view.data.get("canary_id" if phase == "canary" else "experiment_id")
        if cycle > view.cycle or (cycle == view.cycle and experiment_id != identity):
            raise ValueError("experiment identity mismatch")
        result = await host_call(
            metrics.read(
                view,
                who,
                cycle=cycle,
                phase=phase,
                experiment_id=experiment_id,
                start=start,
                end=end,
                max_points=max_points,
            )
        )
        if (result.run_id, result.cycle, result.phase, result.experiment_id) != (
            run_id,
            cycle,
            phase,
            experiment_id,
        ):
            raise ValueError("host metric scope mismatch")
        if result.fresh_until < result.observed_at or any(
            len(series.points) > max_points
            or any(not start <= point.at <= end for point in series.points)
            for series in result.series
        ):
            raise ValueError("host metric bounds mismatch")
        return result.model_dump(mode="json")

    assets = Path(__file__).parent / "static"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets / "assets"), name="assets")

    @app.get("/")
    async def index() -> Response:
        if not (assets / "index.html").is_file():
            raise HTTPException(
                503, "Manager assets missing; run the frontend build before packaging"
            )
        return FileResponse(assets / "index.html")

    return app
