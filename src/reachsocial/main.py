from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .api import router as api_router
from .catalog import get_catalog
from .config import get_settings
from .db import init_db
from .errors import ReachSocialError
from .observability import RequestLoggingMiddleware, configure_logging
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
    logging.getLogger("reachsocial").info(
        "ReachSocial started with %s services", len(catalog.services)
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="ReachSocial API",
        summary="Provider-neutral social data services for B2B clients and agents.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
    app.include_router(api_router)
    settings = get_settings()
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
    async def reachsocial_error(_request: Request, error: ReachSocialError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": error.code, "message": error.message}},
        )

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException) -> JSONResponse:
        detail = error.detail if isinstance(error.detail, dict) else {"message": str(error.detail)}
        return JSONResponse(
            status_code=error.status_code, content={"error": detail}, headers=error.headers
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
            "home.html", {"request": request, "catalog": request.app.state.catalog}
        )

    @app.get("/catalog", include_in_schema=False)
    async def catalog_page(request: Request):
        return templates.TemplateResponse(
            "catalog.html", {"request": request, "catalog": request.app.state.catalog}
        )

    @app.get("/services/{service_id}", include_in_schema=False)
    async def service_page(service_id: str, request: Request):
        service = request.app.state.catalog.by_id(service_id)
        if service is None:
            return templates.TemplateResponse(
                "not_found.html", {"request": request}, status_code=404
            )
        return templates.TemplateResponse("service.html", {"request": request, "service": service})

    @app.get("/docs/api", include_in_schema=False)
    async def docs_page(request: Request):
        return templates.TemplateResponse("docs.html", {"request": request})

    return app


app = create_app()
