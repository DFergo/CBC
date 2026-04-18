# Adapted from HRDDHelper/src/backend/main.py
# Sprint 1 scope: minimal FastAPI app with admin auth + SPA serving.
# Polling loop, lifecycle scanner, RAG, etc. land in later sprints.
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.v1.admin.auth import router as auth_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CBC backend started (Sprint 1 — scaffolding)")
    yield


app = FastAPI(title="CBC Backend", version="0.1.0", lifespan=lifespan)

app.include_router(auth_router)

ADMIN_DIST = Path("/app/admin/dist")


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


# Admin SPA — mounted AFTER API routes so /admin/* (API) wins over /{path} (SPA fallback).
if ADMIN_DIST.exists():
    app.mount("/assets", StaticFiles(directory=ADMIN_DIST / "assets"), name="admin-assets")

    @app.get("/{full_path:path}")
    async def serve_admin_spa(full_path: str):
        file_path = ADMIN_DIST / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(ADMIN_DIST / "index.html")
