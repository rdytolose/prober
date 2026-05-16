"""Coordinator HTTP API + HTML dashboard."""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field
from sqlalchemy import case, desc, func, select

from .config import CoordinatorSettings, load_settings
from .db import Database, Job, Outcome, Prober, ProberToken

log = logging.getLogger(__name__)


COOKIE_NAME = "vpnprober_admin"
JOB_ACTIVE_STATUSES = ("pending", "claimed")
JOB_TERMINAL_STATUSES = ("done", "failed", "cancelled")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class JobCreate(BaseModel):
    links: list[str] = Field(default_factory=list)
    test_urls: list[str] = Field(default_factory=list)
    label: str | None = None


class ProberRegister(BaseModel):
    name: str


class OutcomesPost(BaseModel):
    job_id: str
    prober_name: str
    outcomes: list[dict[str, Any]]
    final: bool = False


class TokenCreate(BaseModel):
    label: str = ""


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _admin_token_present(settings: CoordinatorSettings, request: Request) -> str:
    """Pull the candidate admin token from header, cookie, or ?token= query."""
    return (
        _bearer(request)
        or request.cookies.get(COOKIE_NAME, "")
        or request.query_params.get("token", "")
    )


def _is_admin(settings: CoordinatorSettings, request: Request) -> bool:
    tok = _admin_token_present(settings, request)
    return bool(settings.coordinator_admin_token) and secrets.compare_digest(tok, settings.coordinator_admin_token)


async def _is_valid_prober_token(settings: CoordinatorSettings, db: Database, token: str) -> bool:
    if not token:
        return False
    if token in settings.prober_tokens:
        return True
    async with db.session() as session:
        row = (
            await session.execute(
                select(ProberToken).where(ProberToken.token == token, ProberToken.revoked_at.is_(None))
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        row.last_used_at = dt.datetime.now(dt.timezone.utc)
        await session.commit()
        return True


def require_admin(settings: CoordinatorSettings):
    async def _dep(request: Request) -> bool:
        if not _is_admin(settings, request):
            raise HTTPException(status_code=401, detail="invalid admin token")
        return True

    return _dep


def require_prober(settings: CoordinatorSettings, db: Database):
    async def _dep(request: Request) -> str:
        token = _bearer(request)
        if not await _is_valid_prober_token(settings, db, token):
            raise HTTPException(status_code=401, detail="invalid prober token")
        return request.headers.get("X-Prober-Name", "unknown")

    return _dep


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(settings: CoordinatorSettings | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = Database(settings.coordinator_db_url)

    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    jinja = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html"]),
        enable_async=False,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await db.init()
        yield
        await db.dispose()

    app = FastAPI(title="VPN Prober Coordinator", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.jinja = jinja

    prober_auth = require_prober(settings, db)
    admin_auth = require_admin(settings)

    # ---------------- helpers shared by HTML + API ---------------- #

    async def _job_progress(session, job_id: str) -> dict[str, Any]:
        """Aggregated stats: total / done / ok / fail for a job."""
        job = await session.get(Job, job_id)
        if job is None:
            return {"missing": True}
        total = job.n_links or len((job.payload or {}).get("links", []))
        done = (
            await session.execute(
                select(func.count(Outcome.id)).where(Outcome.job_id == job_id)
            )
        ).scalar_one()
        ok = (
            await session.execute(
                select(func.count(Outcome.id)).where(Outcome.job_id == job_id, Outcome.ok.is_(True))
            )
        ).scalar_one()
        fail = done - ok
        return {
            "id": job.id,
            "status": job.status,
            "label": (job.payload or {}).get("label"),
            "claimed_by": job.claimed_by,
            "created_at": _iso(job.created_at),
            "done_at": _iso(job.done_at),
            "total": int(total),
            "done": int(done),
            "ok": int(ok),
            "fail": int(fail),
            "percent": round(100 * done / total, 1) if total else 0.0,
        }

    # ---------------- health ---------------- #
    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok"}

    @app.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/dashboard")

    # ---------------- prober API ---------------- #
    @app.post("/api/v1/probers/register")
    async def register_prober(
        body: ProberRegister,
        prober_name: str = Depends(prober_auth),  # noqa: B008
    ) -> dict[str, Any]:
        async with db.session() as session:
            existing = (
                await session.execute(select(Prober).where(Prober.name == body.name))
            ).scalar_one_or_none()
            now = dt.datetime.now(dt.timezone.utc)
            if existing is None:
                p = Prober(name=body.name, last_seen=now, created_at=now)
                session.add(p)
                await session.commit()
                return {"id": p.id, "name": p.name, "registered": True}
            existing.last_seen = now
            await session.commit()
            return {"id": existing.id, "name": existing.name, "registered": False}

    @app.get("/api/v1/jobs/next")
    async def next_job(prober_name: str = Depends(prober_auth)) -> Response:  # noqa: B008
        async with db.session() as session:
            stmt = (
                select(Job)
                .where(Job.status == "pending")
                .order_by(Job.created_at)
                .limit(1)
            )
            job = (await session.execute(stmt)).scalar_one_or_none()
            if job is None:
                # Refresh prober last_seen on every poll.
                p = (
                    await session.execute(select(Prober).where(Prober.name == prober_name))
                ).scalar_one_or_none()
                if p:
                    p.last_seen = dt.datetime.now(dt.timezone.utc)
                    await session.commit()
                return Response(status_code=204)
            job.status = "claimed"
            job.claimed_by = prober_name
            job.claimed_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
            return JSONResponse(
                content={
                    "id": job.id,
                    "links": job.payload.get("links", []),
                    "test_urls": job.payload.get("test_urls", []),
                    "label": job.payload.get("label"),
                    "n_links": job.n_links,
                }
            )

    @app.get("/api/v1/jobs/{job_id}/status")
    async def job_status_for_prober(job_id: str, prober_name: str = Depends(prober_auth)) -> dict[str, Any]:  # noqa: B008
        async with db.session() as session:
            job = await session.get(Job, job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="not found")
            return {"id": job.id, "status": job.status}

    @app.post("/api/v1/results")
    async def post_results(
        body: OutcomesPost,
        prober_name: str = Depends(prober_auth),  # noqa: B008
    ) -> dict[str, Any]:
        async with db.session() as session:
            job = await session.get(Job, body.job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="job not found")
            for o in body.outcomes:
                session.add(
                    Outcome(
                        job_id=job.id,
                        prober_name=body.prober_name,
                        link=o.get("link", "")[:2000],
                        protocol=o.get("protocol"),
                        remark=o.get("remark") or "",
                        server=o.get("server"),
                        port=o.get("port"),
                        ok=bool(o.get("ok")),
                        error=o.get("error"),
                        engine_startup_ms=o.get("engine_startup_ms"),
                        payload=o,
                    )
                )
            # Refresh prober last_seen
            p = (
                await session.execute(select(Prober).where(Prober.name == prober_name))
            ).scalar_one_or_none()
            if p:
                p.last_seen = dt.datetime.now(dt.timezone.utc)
            if body.final and job.status != "cancelled":
                job.status = "done"
                job.done_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
            return {"accepted": len(body.outcomes), "final": body.final, "job_status": job.status}

    # ---------------- admin API: jobs ---------------- #
    @app.post("/api/v1/jobs", dependencies=[Depends(admin_auth)])
    async def create_job(body: JobCreate) -> dict[str, Any]:
        links = [_clean_link(s) for s in body.links if _clean_link(s)]
        if not links:
            raise HTTPException(status_code=400, detail="links must not be empty")
        async with db.session() as session:
            job = Job(
                payload={"links": links, "test_urls": body.test_urls, "label": body.label},
                n_links=len(links),
            )
            session.add(job)
            await session.commit()
            return {"id": job.id, "status": job.status, "n_links": len(links)}

    @app.get("/api/v1/jobs", dependencies=[Depends(admin_auth)])
    async def list_jobs(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        async with db.session() as session:
            jobs = (
                await session.execute(
                    select(Job).order_by(desc(Job.created_at)).limit(limit).offset(offset)
                )
            ).scalars().all()
            out: list[dict[str, Any]] = []
            for j in jobs:
                progress = await _job_progress(session, j.id)
                out.append(progress)
            return out

    @app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(admin_auth)])
    async def get_job(job_id: str) -> dict[str, Any]:
        async with db.session() as session:
            job = await session.get(Job, job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="not found")
            outcomes = (
                await session.execute(
                    select(Outcome).where(Outcome.job_id == job_id).order_by(Outcome.id)
                )
            ).scalars().all()
            progress = await _job_progress(session, job_id)
            return {
                **progress,
                "payload": job.payload,
                "outcomes": [_outcome_dict(o) for o in outcomes],
            }

    @app.post("/api/v1/jobs/{job_id}/cancel", dependencies=[Depends(admin_auth)])
    async def cancel_job(job_id: str) -> dict[str, Any]:
        async with db.session() as session:
            job = await session.get(Job, job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="not found")
            if job.status in JOB_TERMINAL_STATUSES:
                return {"id": job.id, "status": job.status, "changed": False}
            job.status = "cancelled"
            job.done_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
            return {"id": job.id, "status": job.status, "changed": True}

    @app.delete("/api/v1/jobs/{job_id}", dependencies=[Depends(admin_auth)])
    async def delete_job(job_id: str) -> dict[str, Any]:
        async with db.session() as session:
            job = await session.get(Job, job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="not found")
            await session.delete(job)
            await session.commit()
            return {"id": job_id, "deleted": True}

    # ---------------- admin API: probers + tokens ---------------- #
    @app.get("/api/v1/probers", dependencies=[Depends(admin_auth)])
    async def list_probers() -> list[dict[str, Any]]:
        async with db.session() as session:
            rows = (
                await session.execute(select(Prober).order_by(desc(Prober.last_seen)))
            ).scalars().all()
            out: list[dict[str, Any]] = []
            for p in rows:
                processed = (
                    await session.execute(
                        select(func.count(Outcome.id)).where(Outcome.prober_name == p.name)
                    )
                ).scalar_one()
                out.append(
                    {
                        "id": p.id,
                        "name": p.name,
                        "last_seen": _iso(p.last_seen),
                        "created_at": _iso(p.created_at),
                        "processed_links": int(processed or 0),
                    }
                )
            return out

    @app.post("/api/v1/admin/tokens", dependencies=[Depends(admin_auth)])
    async def create_prober_token(body: TokenCreate) -> dict[str, Any]:
        token = secrets.token_hex(24)
        async with db.session() as session:
            row = ProberToken(label=(body.label or "").strip()[:128], token=token)
            session.add(row)
            await session.commit()
            return {
                "id": row.id,
                "label": row.label,
                "token": token,
                "created_at": _iso(row.created_at),
            }

    @app.get("/api/v1/admin/tokens", dependencies=[Depends(admin_auth)])
    async def list_prober_tokens() -> list[dict[str, Any]]:
        async with db.session() as session:
            rows = (
                await session.execute(select(ProberToken).order_by(desc(ProberToken.created_at)))
            ).scalars().all()
            return [
                {
                    "id": r.id,
                    "label": r.label,
                    "token": r.token,
                    "created_at": _iso(r.created_at),
                    "last_used_at": _iso(r.last_used_at),
                    "revoked_at": _iso(r.revoked_at),
                }
                for r in rows
            ]

    @app.post("/api/v1/admin/tokens/{token_id}/revoke", dependencies=[Depends(admin_auth)])
    async def revoke_prober_token(token_id: str) -> dict[str, Any]:
        async with db.session() as session:
            row = await session.get(ProberToken, token_id)
            if row is None:
                raise HTTPException(status_code=404, detail="not found")
            row.revoked_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
            return {"id": row.id, "revoked": True}

    # ---------------- HTML dashboard ---------------- #
    def _render(name: str, request: Request, **ctx: Any) -> HTMLResponse:
        ctx.setdefault("request_path", request.url.path)
        ctx.setdefault("origin", str(request.base_url).rstrip("/"))
        html = jinja.get_template(name).render(**ctx)
        return HTMLResponse(html)

    def _need_admin_html(request: Request) -> Response | None:
        if _is_admin(settings, request):
            return None
        return HTMLResponse(
            jinja.get_template("login.html").render(
                error=bool(request.query_params.get("token")),
            ),
            status_code=200,
        )

    def _set_cookie_if_token(request: Request, response: Response) -> Response:
        if request.query_params.get("token") and _is_admin(settings, request):
            response.set_cookie(
                COOKIE_NAME,
                request.query_params["token"],
                httponly=True,
                samesite="lax",
                max_age=60 * 60 * 24 * 30,
            )
        return response

    @app.post("/dashboard/login")
    async def dashboard_login_post(request: Request, token: str = Form(...)) -> Response:
        if not settings.coordinator_admin_token or token != settings.coordinator_admin_token:
            return RedirectResponse(url="/dashboard?token=bad", status_code=303)
        resp = RedirectResponse(url="/dashboard", status_code=303)
        resp.set_cookie(
            COOKIE_NAME, token,
            httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30,
        )
        return resp

    @app.get("/dashboard/logout")
    async def dashboard_logout() -> Response:
        resp = RedirectResponse(url="/dashboard", status_code=303)
        resp.delete_cookie(COOKIE_NAME)
        return resp

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request) -> Response:
        gate = _need_admin_html(request)
        if gate is not None:
            return gate
        async with db.session() as session:
            jobs = (
                await session.execute(select(Job).order_by(desc(Job.created_at)).limit(20))
            ).scalars().all()
            probers = (
                await session.execute(select(Prober).order_by(desc(Prober.last_seen)))
            ).scalars().all()
            ok_sum = func.sum(case((Outcome.ok.is_(True), 1), else_=0))
            stats_by_protocol = (
                await session.execute(
                    select(Outcome.protocol, func.count(Outcome.id), ok_sum)
                    .group_by(Outcome.protocol)
                )
            ).all()
            job_progress = [await _job_progress(session, j.id) for j in jobs]
            total_outcomes = (await session.execute(select(func.count(Outcome.id)))).scalar_one() or 0
            total_ok = (
                await session.execute(select(func.count(Outcome.id)).where(Outcome.ok.is_(True)))
            ).scalar_one() or 0
        ctx = dict(
            jobs=job_progress,
            probers=[
                {"name": p.name, "last_seen": _iso(p.last_seen), "id": p.id} for p in probers
            ],
            stats_by_protocol=[
                {"protocol": p or "unknown", "total": int(t or 0), "ok": int(o or 0)}
                for (p, t, o) in stats_by_protocol
            ],
            total_outcomes=int(total_outcomes),
            total_ok=int(total_ok),
            active_page="dashboard",
        )
        resp = _render("dashboard.html", request, **ctx)
        return _set_cookie_if_token(request, resp)

    @app.get("/dashboard/jobs", response_class=HTMLResponse)
    async def dashboard_jobs(request: Request, limit: int = 100) -> Response:
        gate = _need_admin_html(request)
        if gate is not None:
            return gate
        async with db.session() as session:
            jobs = (
                await session.execute(select(Job).order_by(desc(Job.created_at)).limit(limit))
            ).scalars().all()
            job_progress = [await _job_progress(session, j.id) for j in jobs]
        resp = _render(
            "jobs.html", request, jobs=job_progress, active_page="jobs",
        )
        return _set_cookie_if_token(request, resp)

    @app.get("/dashboard/jobs/{job_id}", response_class=HTMLResponse)
    async def dashboard_job(job_id: str, request: Request) -> Response:
        gate = _need_admin_html(request)
        if gate is not None:
            return gate
        async with db.session() as session:
            job = await session.get(Job, job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="job not found")
            outcomes = (
                await session.execute(
                    select(Outcome).where(Outcome.job_id == job_id).order_by(desc(Outcome.id)).limit(500)
                )
            ).scalars().all()
            progress = await _job_progress(session, job_id)
        resp = _render(
            "job.html",
            request,
            job={
                **progress,
                "test_urls": (job.payload or {}).get("test_urls", []),
            },
            outcomes=[_outcome_dict(o) for o in outcomes],
            active_page="jobs",
        )
        return _set_cookie_if_token(request, resp)

    @app.get("/dashboard/new", response_class=HTMLResponse)
    async def dashboard_new(request: Request) -> Response:
        gate = _need_admin_html(request)
        if gate is not None:
            return gate
        resp = _render("new_job.html", request, active_page="new", error=None)
        return _set_cookie_if_token(request, resp)

    @app.post("/dashboard/new")
    async def dashboard_new_submit(
        request: Request,
        links_text: str = Form(default=""),
        urls_text: str = Form(default=""),
        label: str = Form(default=""),
        links_file: UploadFile | None = File(default=None),  # noqa: B008
    ) -> Response:
        if not _is_admin(settings, request):
            return RedirectResponse(url="/dashboard", status_code=303)
        # Combine textarea + uploaded file
        raw = links_text or ""
        if links_file is not None and links_file.filename:
            try:
                raw += "\n" + (await links_file.read()).decode("utf-8", errors="replace")
            except Exception as exc:
                resp = _render("new_job.html", request, active_page="new", error=f"file read failed: {exc!s}")
                return _set_cookie_if_token(request, resp)
        links = [_clean_link(line) for line in raw.splitlines()]
        links = [s for s in links if s]
        urls = [s.strip() for s in re.split(r"[\s,]+", urls_text or "") if s.strip()]
        if not links:
            resp = _render("new_job.html", request, active_page="new",
                           error="No links found (drag-drop a file or paste at least one link).")
            return _set_cookie_if_token(request, resp)
        async with db.session() as session:
            job = Job(
                payload={"links": links, "test_urls": urls, "label": label.strip() or None},
                n_links=len(links),
            )
            session.add(job)
            await session.commit()
            job_id = job.id
        return RedirectResponse(url=f"/dashboard/jobs/{job_id}", status_code=303)

    @app.post("/dashboard/jobs/{job_id}/cancel")
    async def dashboard_cancel(request: Request, job_id: str) -> Response:
        if not _is_admin(settings, request):
            return RedirectResponse(url="/dashboard", status_code=303)
        async with db.session() as session:
            job = await session.get(Job, job_id)
            if job is not None and job.status not in JOB_TERMINAL_STATUSES:
                job.status = "cancelled"
                job.done_at = dt.datetime.now(dt.timezone.utc)
                await session.commit()
        return RedirectResponse(url=f"/dashboard/jobs/{job_id}", status_code=303)

    @app.get("/dashboard/nodes", response_class=HTMLResponse)
    async def dashboard_nodes(request: Request) -> Response:
        gate = _need_admin_html(request)
        if gate is not None:
            return gate
        async with db.session() as session:
            tokens = (
                await session.execute(select(ProberToken).order_by(desc(ProberToken.created_at)))
            ).scalars().all()
            probers = (
                await session.execute(select(Prober).order_by(desc(Prober.last_seen)))
            ).scalars().all()
            prober_rows: list[dict[str, Any]] = []
            for p in probers:
                processed = (
                    await session.execute(
                        select(func.count(Outcome.id)).where(Outcome.prober_name == p.name)
                    )
                ).scalar_one()
                prober_rows.append(
                    {
                        "id": p.id,
                        "name": p.name,
                        "last_seen": _iso(p.last_seen),
                        "processed_links": int(processed or 0),
                    }
                )
        flash_token = request.query_params.get("new_token")
        flash_label = request.query_params.get("new_label", "")
        resp = _render(
            "nodes.html",
            request,
            tokens=[
                {
                    "id": t.id,
                    "label": t.label or "(no label)",
                    "token_masked": _mask(t.token),
                    "token_full": t.token,
                    "created_at": _iso(t.created_at),
                    "last_used_at": _iso(t.last_used_at),
                    "revoked": t.revoked_at is not None,
                }
                for t in tokens
            ],
            probers=prober_rows,
            origin=str(request.base_url).rstrip("/"),
            flash_token=flash_token,
            flash_label=flash_label,
            active_page="nodes",
        )
        return _set_cookie_if_token(request, resp)

    @app.post("/dashboard/nodes/create")
    async def dashboard_nodes_create(request: Request, label: str = Form(default="")) -> Response:
        if not _is_admin(settings, request):
            return RedirectResponse(url="/dashboard", status_code=303)
        token = secrets.token_hex(24)
        async with db.session() as session:
            row = ProberToken(label=label.strip()[:128], token=token)
            session.add(row)
            await session.commit()
        return RedirectResponse(
            url=f"/dashboard/nodes?new_token={token}&new_label={label.strip()[:128]}",
            status_code=303,
        )

    @app.post("/dashboard/nodes/{token_id}/revoke")
    async def dashboard_nodes_revoke(request: Request, token_id: str) -> Response:
        if not _is_admin(settings, request):
            return RedirectResponse(url="/dashboard", status_code=303)
        async with db.session() as session:
            row = await session.get(ProberToken, token_id)
            if row is not None and row.revoked_at is None:
                row.revoked_at = dt.datetime.now(dt.timezone.utc)
                await session.commit()
        return RedirectResponse(url="/dashboard/nodes", status_code=303)

    return app


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _iso(d: dt.datetime | None) -> str | None:
    if d is None:
        return None
    return d.isoformat()


def _clean_link(s: str) -> str:
    s = (s or "").strip()
    if not s or s.startswith("#"):
        return ""
    return s


def _mask(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 12:
        return "•" * len(token)
    return token[:6] + "…" + token[-4:]


def _outcome_dict(o: Outcome) -> dict[str, Any]:
    return {
        "id": o.id,
        "job_id": o.job_id,
        "prober_name": o.prober_name,
        "link": o.link,
        "protocol": o.protocol,
        "remark": o.remark,
        "server": o.server,
        "port": o.port,
        "ok": o.ok,
        "error": o.error,
        "engine_startup_ms": o.engine_startup_ms,
        "tests": (o.payload or {}).get("tests"),
        "meta": (o.payload or {}).get("meta"),
        "created_at": _iso(o.created_at),
    }
