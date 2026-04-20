# Adapted from HRDDHelper/src/backend/main.py
# Sprint 4A: + frontend registry, health-only polling loop, per-frontend
# branding + session-settings overrides.
import asyncio
import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.v1.admin.auth import router as auth_router
from src.api.v1.admin.companies import router as companies_router
from src.api.v1.admin.prompts import router as prompts_router
from src.api.v1.admin.rag import router as rag_router
from src.api.v1.admin.knowledge import router as knowledge_router
from src.api.v1.admin.llm import router as llm_router
from src.api.v1.admin.smtp import router as smtp_router
from src.api.v1.admin.contacts import router as contacts_router
from src.api.v1.admin.frontends import router as frontends_router
from src.api.v1.admin.resolvers import router as resolvers_router
from src.api.v1.admin.branding import router as branding_router
from src.api.v1.admin.guardrails import router as admin_guardrails_router
from src.api.v1.admin.sessions import router as admin_sessions_router
from src.api.v1.auth import router as auth_router_v1
from src.api.v1.guardrails import router as guardrails_router_v1
from src.api.v1.sessions.uploads import router as session_uploads_router
from src.services._paths import (
    ensure_dirs,
    PROMPTS_DIR,
    KNOWLEDGE_DIR,
    GLOSSARY_FILE,
    ORGANIZATIONS_FILE,
)
from src.services.polling import polling_loop
from src.services.smtp_service import check_smtp_health

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

DEFAULTS_PROMPTS = Path(__file__).parent / "prompts"
DEFAULTS_KNOWLEDGE = Path(__file__).parent / "knowledge"


def ensure_defaults() -> None:
    ensure_dirs()
    if DEFAULTS_PROMPTS.is_dir():
        for src in DEFAULTS_PROMPTS.glob("*.md"):
            dst = PROMPTS_DIR / src.name
            if not dst.exists():
                shutil.copy2(src, dst)
                logger.info(f"Installed default prompt: {dst.name}")
    for src_name, dst in (("glossary.json", GLOSSARY_FILE), ("organizations.json", ORGANIZATIONS_FILE)):
        src = DEFAULTS_KNOWLEDGE / src_name
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            logger.info(f"Installed default knowledge: {dst.name}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.services import rag_watcher
    from src.services.session_lifecycle import lifecycle_loop

    ensure_defaults()
    asyncio.create_task(check_smtp_health())
    poll_task = asyncio.create_task(polling_loop())
    lifecycle_task = asyncio.create_task(lifecycle_loop())
    rag_watcher.start()
    logger.info("CBC backend started (Sprint 7 — chat engine + lifecycle scanner)")
    yield
    poll_task.cancel()
    lifecycle_task.cancel()
    for t in (poll_task, lifecycle_task):
        try:
            await t
        except asyncio.CancelledError:
            pass
    rag_watcher.stop()


app = FastAPI(title="CBC Backend", version="0.4.0", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(frontends_router)
app.include_router(companies_router)
app.include_router(prompts_router)
app.include_router(rag_router)
app.include_router(knowledge_router)
app.include_router(llm_router)
app.include_router(smtp_router)
app.include_router(contacts_router)
app.include_router(resolvers_router)
app.include_router(branding_router)
app.include_router(admin_guardrails_router)
app.include_router(admin_sessions_router)
app.include_router(session_uploads_router)
app.include_router(auth_router_v1)
app.include_router(guardrails_router_v1)

ADMIN_DIST = Path("/app/admin/dist")


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


if ADMIN_DIST.exists():
    app.mount("/assets", StaticFiles(directory=ADMIN_DIST / "assets"), name="admin-assets")

    @app.get("/{full_path:path}")
    async def serve_admin_spa(full_path: str):
        file_path = ADMIN_DIST / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(ADMIN_DIST / "index.html")
