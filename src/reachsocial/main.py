from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .alerts import alert_loop
from .api import router as api_router
from .catalog import get_catalog
from .config import get_settings
from .db import init_db
from .errors import ReachSocialError
from .jobs import JobWorker
from .maintenance import prune_operational_records
from .observability import RequestLoggingMiddleware, configure_logging
from .payments import ReachSocialX402Middleware, mainnet_x402_safety_errors, x402_is_configured
from .runtime import RuntimeState
from .services import ExecutionService, sync_service_records

ROOT = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(ROOT / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging()
    catalog = get_catalog()
    if not settings.is_production:
        init_db()
    from .db import SessionLocal

    with SessionLocal() as session:
        sync_service_records(session, catalog)
    app.state.settings = settings
    app.state.catalog = catalog
    app.state.runtime = RuntimeState()
    app.state.executor = ExecutionService(catalog, app.state.runtime)
    app.state.job_worker = JobWorker(catalog, app.state.executor)
    async def maintenance_loop() -> None:
        while True:
            try:
                deleted = prune_operational_records()
                logging.getLogger("reachsocial").info(
                    "maintenance_pruned counts=%s", deleted
                )
            except Exception:
                logging.getLogger("reachsocial").exception("maintenance_prune_failed")
            await asyncio.sleep(settings.maintenance_interval_hours * 60 * 60)

    maintenance_task = asyncio.create_task(maintenance_loop())
    job_task = asyncio.create_task(app.state.job_worker.run())
    alert_task = asyncio.create_task(alert_loop())
    logging.getLogger("reachsocial").info(
        "ReachSocial started with %s services", len(catalog.services)
    )
    try:
        yield
    finally:
        maintenance_task.cancel()
        job_task.cancel()
        alert_task.cancel()
        await asyncio.gather(maintenance_task, job_task, alert_task, return_exceptions=True)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ReachSocial API",
        summary="Provider-neutral social data services for B2B clients and agents.",
        version="0.1.0",
        lifespan=lifespan,
        servers=[
            {
                "url": str(settings.public_base_url).rstrip("/"),
                "description": "Public ReachSocial API",
            }
        ],
    )
    app.add_middleware(RequestLoggingMiddleware)
    if settings.x402_enabled:
        if not x402_is_configured(settings):
            raise RuntimeError(
                "X402_ENABLED requires CDP_API_KEY_ID, CDP_API_KEY_SECRET, "
                "X402_PAY_TO, and X402_FACILITATOR_URL"
            )
        mainnet_errors = mainnet_x402_safety_errors(settings, get_catalog())
        if mainnet_errors:
            raise RuntimeError("Base mainnet x402 is blocked: " + "; ".join(mainnet_errors))
        app.add_middleware(
            ReachSocialX402Middleware,
            settings=settings,
            catalog=get_catalog(),
        )
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    app.include_router(api_router)
    if settings.mcp_enabled:
        from .mcp import make_mcp_app

        app.mount("/mcp", make_mcp_app(get_catalog()))
    else:

        @app.api_route(
            "/mcp/{path:path}", methods=["GET", "POST", "DELETE"], include_in_schema=False
        )
        async def disabled_mcp(path: str):
            del path
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "mcp_disabled", "message": "MCP is not enabled"}},
            )

    @app.exception_handler(ReachSocialError)
    async def reachsocial_error(request: Request, error: ReachSocialError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "retryable": error.retryable,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        detail = error.detail if isinstance(error.detail, dict) else {"message": str(error.detail)}
        detail.setdefault("retryable", False)
        detail.setdefault("request_id", getattr(request.state, "request_id", None))
        return JSONResponse(
            status_code=error.status_code, content={"error": detail}, headers=error.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_input",
                    "message": "The request body or parameters are invalid.",
                    "retryable": False,
                    "request_id": getattr(request.state, "request_id", None),
                    "details": error.errors(),
                }
            },
        )

    @app.get("/healthz", tags=["Operations"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["Operations"])
    async def readyz(request: Request) -> dict[str, object]:
        from sqlalchemy import text

        from .db import SessionLocal

        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ready", "services": len(request.app.state.catalog.services)}

    @app.get("/status.json", include_in_schema=False)
    async def status_json(request: Request) -> dict[str, object]:
        settings = request.app.state.settings
        return {
            "status": "operational",
            "services": len(request.app.state.catalog.public_services()),
            "network": settings.x402_network if settings.x402_enabled else "payments-disabled",
        }

    @app.get("/llms.txt", include_in_schema=False)
    async def llms(request: Request) -> str:
        catalog = request.app.state.catalog
        enabled = [f"- {item.id}: {item.description}" for item in catalog.public_services()]
        return (
            "# ReachSocial\n\nProvider-neutral social data API.\n\n## Enabled services\n"
            + "\n".join(enabled)
        )

    @app.get("/", include_in_schema=False)
    async def home(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={"catalog": request.app.state.catalog},
        )

    @app.get("/catalog", include_in_schema=False)
    async def catalog_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="catalog.html",
            context={"catalog": request.app.state.catalog},
        )

    @app.get("/services/{service_id}", include_in_schema=False)
    async def service_page(service_id: str, request: Request):
        service = request.app.state.catalog.by_id(service_id)
        if service is None or not (service.enabled and service.public):
            return templates.TemplateResponse(
                request=request,
                name="not_found.html",
                context={},
                status_code=404,
            )
        return templates.TemplateResponse(
            request=request,
            name="service.html",
            context={"service": service},
        )

    @app.get("/docs/api", include_in_schema=False)
    async def docs_page(request: Request):
        return templates.TemplateResponse(request=request, name="docs.html", context={})

    @app.get("/pricing", include_in_schema=False)
    async def pricing_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="pricing.html",
            context={"catalog": request.app.state.catalog},
        )

    @app.get("/status", include_in_schema=False)
    async def status_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="status.html",
            context={"catalog": request.app.state.catalog},
        )

    @app.get("/contact", include_in_schema=False)
    async def contact_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="contact.html",
            context={"support_email": request.app.state.settings.support_email},
        )

    @app.get("/legal/{document}", include_in_schema=False)
    async def legal_page(document: str, request: Request):
        pages = {
            "terms": ("Terms of Service", "terms.html"),
            "privacy": ("Privacy Notice", "privacy.html"),
            "acceptable-use": ("Acceptable Use", "acceptable_use.html"),
            "refunds": ("Refund Policy", "refunds.html"),
        }
        page = pages.get(document)
        if page is None:
            return templates.TemplateResponse(
                request=request, name="not_found.html", context={}, status_code=404
            )
        return templates.TemplateResponse(
            request=request,
            name=page[1],
            context={"title": page[0], "support_email": request.app.state.settings.support_email},
        )

    return app


app = create_app()
