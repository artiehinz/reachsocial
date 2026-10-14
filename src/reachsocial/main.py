from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .alerts import alert_loop
from .api import router as api_router
from .catalog import get_catalog
from .config import get_settings, x402_network_label
from .cors import PublicApiCorsMiddleware
from .credit_budget import reconcile_pending as reconcile_credit_reservations
from .db import init_db
from .discovery import (
    agent_text,
    api_catalog,
    build_openapi_schema,
    llms_text,
    mcp_server_card,
    robots_text,
    sitemap_xml,
)
from .errors import ReachSocialError
from .jobs import JobWorker
from .maintenance import prune_operational_records
from .observability import (
    RequestBodyLimitMiddleware,
    RequestBodyTooLarge,
    RequestLoggingMiddleware,
    configure_logging,
)
from .payment_metadata import public_payment_metadata
from .payments import (
    MainnetAcceptanceX402Middleware,
    MainnetCanaryX402Middleware,
    ReachSocialX402Middleware,
    mainnet_acceptance_safety_errors,
    mainnet_canary_safety_errors,
    mainnet_x402_safety_errors,
    x402_is_configured,
)
from .runtime import RuntimeState
from .services import ExecutionService, sync_service_records

ROOT = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(ROOT / "templates"))

EXAMPLE_RESPONSE = json.loads((ROOT / "examples" / "instagram-profile.json").read_text())
EXAMPLE_RESPONSE_JSON = json.dumps(EXAMPLE_RESPONSE, indent=2)
BROWSER_EXAMPLE = (ROOT / "examples" / "browser" / "reachsocial-client.ts").read_text()
AGENT_SETUP_PROMPT = (
    "Read https://reachsocial.dev/agent.txt and help me set up ReachSocial. "
    "Fetch https://reachsocial.dev/v1/services and https://reachsocial.dev/status.json for "
    "current prices, availability, and payment network; do not rely on search snippets. "
    "Help me connect an x402-compatible wallet and ask for a spending limit. Verify the "
    "payment challenge before signing. Keep wallet secrets out of chat."
)

DISCOVERY_CACHE_PATHS = {
    "/openapi.json",
    "/llms.txt",
    "/agent.md",
    "/agent.txt",
    "/.well-known/api-catalog",
    "/robots.txt",
    "/sitemap.xml",
}
PUBLIC_PAGE_PATHS = {
    "/",
    "/catalog",
    "/docs/api",
    "/pricing",
    "/contact",
    "/status",
}


def public_cache_control(path: str) -> str | None:
    if path.startswith("/static/"):
        return "public, max-age=300, s-maxage=86400, stale-while-revalidate=604800"
    if path in DISCOVERY_CACHE_PATHS or path in {"/v1/services", "/v1/catalog"}:
        return "public, max-age=60, s-maxage=300, stale-while-revalidate=600"
    if path.startswith("/v1/services/"):
        return "public, max-age=60, s-maxage=300, stale-while-revalidate=600"
    if path in PUBLIC_PAGE_PATHS or path.startswith("/services/") or path.startswith("/legal/"):
        return "public, max-age=60, s-maxage=120, stale-while-revalidate=300"
    return None


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
        reconciled = reconcile_credit_reservations(session)
        if reconciled:
            logging.getLogger("reachsocial").info(
                "provider_credit_reservations_reconciled count=%s", reconciled
            )
    app.state.settings = settings
    app.state.catalog = catalog
    app.state.runtime = RuntimeState(
        cache_max_entries=settings.runtime_cache_max_entries,
        cache_max_bytes=settings.runtime_cache_max_bytes,
        idle_seconds=settings.runtime_state_idle_seconds,
    )
    app.state.executor = ExecutionService(catalog, app.state.runtime)
    app.state.job_worker = JobWorker(catalog, app.state.executor)

    async def maintenance_loop() -> None:
        while True:
            try:
                deleted = prune_operational_records()
                await app.state.runtime.prune()
                logging.getLogger("reachsocial").info("maintenance_pruned counts=%s", deleted)
            except Exception:
                logging.getLogger("reachsocial").exception("maintenance_prune_failed")
            await asyncio.sleep(settings.maintenance_interval_hours * 60 * 60)

    maintenance_task = asyncio.create_task(maintenance_loop())
    job_task = asyncio.create_task(app.state.job_worker.run())
    alert_task = asyncio.create_task(
        alert_loop(
            app.state.runtime,
            frozenset(service.id for service in catalog.public_services()),
        )
    )
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

    @app.middleware("http")
    async def cache_control(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        header_value = (
            public_cache_control(request.url.path)
            if request.method in {"GET", "HEAD"} and 200 <= response.status_code < 300
            else None
        )
        response.headers.setdefault("Cache-Control", header_value or "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if (
            response.headers.get("content-type", "").startswith("text/html")
            and request.url.path != "/docs"
            and request.url.path != "/redoc"
        ):
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; base-uri 'none'; object-src 'none'; "
                "frame-ancestors 'none'; form-action 'self'",
            )
        return response

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
    if settings.mainnet_x402_canary_enabled:
        canary_errors = mainnet_canary_safety_errors(settings, get_catalog())
        if canary_errors:
            raise RuntimeError("Base mainnet canary is blocked: " + "; ".join(canary_errors))
        app.add_middleware(
            MainnetCanaryX402Middleware,
            settings=settings,
            catalog=get_catalog(),
        )
    if settings.mainnet_x402_acceptance_enabled:
        acceptance_errors = mainnet_acceptance_safety_errors(settings, get_catalog())
        if acceptance_errors:
            raise RuntimeError(
                "Base mainnet acceptance is blocked: " + "; ".join(acceptance_errors)
            )
        app.add_middleware(
            MainnetAcceptanceX402Middleware,
            settings=settings,
            catalog=get_catalog(),
        )
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=settings.max_request_body_bytes,
        max_payment_header_bytes=settings.max_payment_header_bytes,
    )
    # This is intentionally last so preflights are answered before payment middleware.
    app.add_middleware(PublicApiCorsMiddleware, catalog=get_catalog())
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    app.include_router(api_router)

    @app.get("/mcp/server-card", include_in_schema=False)
    @app.get("/mcp.json", include_in_schema=False)
    @app.get("/.well-known/mcp.json", include_in_schema=False)
    async def mcp_card():
        if not settings.mcp_enabled:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "mcp_disabled",
                        "message": "MCP is not enabled; use the documented REST API.",
                    }
                },
            )
        return JSONResponse(
            mcp_server_card(settings),
            media_type="application/mcp-server-card+json",
        )

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

    @app.exception_handler(RequestBodyTooLarge)
    async def request_too_large(request: Request, error: RequestBodyTooLarge) -> JSONResponse:
        del error
        return JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "request_too_large",
                    "message": "Request body is too large",
                    "retryable": False,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    @app.get("/healthz", tags=["Operations"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["Operations"])
    async def readyz(request: Request) -> Response:
        from sqlalchemy import text

        from .db import SessionLocal

        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        settings = request.app.state.settings
        pause_reason = (
            "operator_pause"
            if settings.public_payments_paused
            else request.app.state.runtime.public_payments_paused_reason
        )
        if pause_reason:
            return JSONResponse(
                status_code=503,
                content={"status": "payments_paused", "reason": pause_reason},
            )
        degraded_services = request.app.state.runtime.degraded_public_services()
        if degraded_services:
            return JSONResponse(
                {
                    "status": "degraded",
                    "services": len(request.app.state.catalog.services),
                    "degraded_services": degraded_services,
                }
            )
        return JSONResponse(
            {"status": "ready", "services": len(request.app.state.catalog.services)}
        )

    @app.get("/status.json", include_in_schema=False)
    async def status_json(request: Request) -> dict[str, object]:
        settings = request.app.state.settings
        catalog = request.app.state.catalog
        degraded_services = request.app.state.runtime.degraded_public_services()
        globally_paused = bool(
            settings.public_payments_paused
            or request.app.state.runtime.public_payments_paused_reason
        )
        return {
            "status": (
                "payments_paused"
                if globally_paused
                else "degraded"
                if degraded_services
                else "operational"
            ),
            "services": len(catalog.public_services()),
            "catalog_services": len(catalog.discoverable_services()),
            "mcp": "available" if settings.mcp_enabled else "disabled",
            "network": settings.x402_network if settings.x402_enabled else "payments-disabled",
            "payment": public_payment_metadata(settings),
            "degraded_services": degraded_services,
        }

    @app.get("/llms.txt", include_in_schema=False)
    async def llms(request: Request) -> PlainTextResponse:
        return PlainTextResponse(
            llms_text(request.app.state.catalog, request.app.state.settings),
            media_type="text/plain; charset=utf-8",
        )

    @app.get("/agent.md", include_in_schema=False)
    @app.get("/agent.txt", include_in_schema=False)
    async def agent_guide(request: Request) -> PlainTextResponse:
        return PlainTextResponse(
            agent_text(request.app.state.catalog, request.app.state.settings),
            media_type=(
                "text/plain; charset=utf-8"
                if request.url.path == "/agent.txt"
                else "text/markdown; charset=utf-8"
            ),
        )

    @app.get("/.well-known/api-catalog", include_in_schema=False)
    async def well_known_api_catalog(request: Request) -> JSONResponse:
        return JSONResponse(
            api_catalog(request.app.state.settings),
            media_type="application/linkset+json",
        )

    @app.get("/robots.txt", include_in_schema=False)
    async def robots(request: Request) -> PlainTextResponse:
        return PlainTextResponse(
            robots_text(request.app.state.settings), media_type="text/plain; charset=utf-8"
        )

    @app.get("/sitemap.xml", include_in_schema=False)
    async def sitemap(request: Request) -> Response:
        return Response(
            sitemap_xml(request.app.state.catalog, request.app.state.settings),
            media_type="application/xml",
        )

    @app.get("/", include_in_schema=False)
    async def home(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "catalog": request.app.state.catalog,
                "payment_network": x402_network_label(request.app.state.settings.x402_network),
                "example_response": EXAMPLE_RESPONSE_JSON,
                "agent_setup_prompt": AGENT_SETUP_PROMPT,
            },
            headers={
                "Link": (
                    '</.well-known/api-catalog>; rel="api-catalog"; '
                    'type="application/linkset+json", </agent.md>; rel="alternate"; '
                    'type="text/markdown"'
                )
            },
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
        if service is None:
            return templates.TemplateResponse(
                request=request,
                name="not_found.html",
                context={},
                status_code=404,
            )
        return templates.TemplateResponse(
            request=request,
            name="service.html",
            context={
                "service": service,
                "payment_network": x402_network_label(request.app.state.settings.x402_network),
            },
        )

    @app.get("/docs/api", include_in_schema=False)
    async def docs_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="docs.html",
            context={
                "payment_network": x402_network_label(request.app.state.settings.x402_network),
                "payment": public_payment_metadata(request.app.state.settings),
                "browser_example": BROWSER_EXAMPLE,
                "example_response": EXAMPLE_RESPONSE_JSON,
                "agent_setup_prompt": AGENT_SETUP_PROMPT,
                "minimum_payment_atomic": min(
                    service.price_cents for service in request.app.state.catalog.public_services()
                )
                * 10_000,
            },
        )

    @app.get("/pricing", include_in_schema=False)
    async def pricing_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="pricing.html",
            context={
                "catalog": request.app.state.catalog,
                "payment_network": x402_network_label(request.app.state.settings.x402_network),
            },
        )

    @app.get("/status", include_in_schema=False)
    async def status_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="status.html",
            context={
                "catalog": request.app.state.catalog,
                "payment_network": x402_network_label(request.app.state.settings.x402_network),
            },
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

    openapi_cache: dict[str, object] | None = None

    def custom_openapi() -> dict[str, object]:
        nonlocal openapi_cache
        if openapi_cache is None:
            openapi_cache = build_openapi_schema(app, get_catalog())
        return openapi_cache

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app


app = create_app()
