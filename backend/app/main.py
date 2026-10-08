import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.errors import install_error_handlers
from app.ingestion.webhook import router as webhook_router
from app.logging_setup import configure_logging

log = logging.getLogger("app.http")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.validate_for_runtime()

    app = FastAPI(
        title="WhatsApp Sales Dashboard API",
        version="1.0.0",
        description="Unified data from all connected WhatsApp Business numbers.",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    install_error_handlers(app)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next) -> Response:  # noqa: ANN001
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        path = request.url.path
        if path.startswith("/webhooks/"):
            path = "/".join(path.split("/")[:3]) + "/***"  # never log webhook tokens
        if not path.startswith("/health"):
            log.info(
                "request",
                extra={
                    "ctx": {
                        "request_id": request_id,
                        "method": request.method,
                        "path": path,
                        "status": response.status_code,
                        "ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                },
            )
        return response

    @app.get("/health/live", tags=["health"], summary="Process is up")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"], summary="Database reachable")
    def ready() -> dict[str, str]:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    app.include_router(webhook_router)
    _include_api(app)
    _mount_frontend(app, settings.frontend_dist_dir)
    return app


def _include_api(app: FastAPI) -> None:
    from app.api import router as api_router

    app.include_router(api_router, prefix="/api/v1")


def _mount_frontend(app: FastAPI, dist_dir: str | None) -> None:
    """Serve the built dashboard (single-image deployment)."""
    if not dist_dir or not Path(dist_dir, "index.html").is_file():
        return
    dist = Path(dist_dir).resolve()
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})


app = create_app()
