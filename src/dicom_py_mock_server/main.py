"""Main FastAPI application entry point for dicom-py-mock-server."""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from dicom_py_mock_server.api import mcp_router, router
from dicom_py_mock_server.api.routes import mwl_service, scp_service
from dicom_py_mock_server.config import config
from dicom_py_mock_server.logging_config import get_logger, setup_logging

# Initialize logging system
setup_logging(config)
logger = get_logger(__name__)

STARTUP_NOTICE = "Created by Gosmart.Health (info@gosmart.healt) 2026, Apache 2.0 License, Not for clinical use."


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event context manager for FastAPI application."""
    logger.info(STARTUP_NOTICE)
    logger.info("app_starting", app_name=config.app_name, version=config.app_version)

    # 1. Seed initial active mock studies across the retention window
    seeded = mwl_service.seed_initial_entries(count=10)
    logger.info("initial_mock_studies_seeded", count=len(seeded))

    # 2. Start background MWL automated generation loop
    mwl_service.start_auto_generation()

    # 3. Start DICOM SCP listener (C-ECHO, C-FIND, C-MOVE, C-STORE, MWL)
    try:
        scp_service.start()
        logger.info(
            "dicom_scp_started_on_startup",
            ae_title=scp_service.ae_title,
            port=scp_service.port,
            is_running=scp_service.is_running,
        )
    except Exception as exc:
        logger.error("failed_to_start_dicom_scp_on_startup", error=str(exc))

    yield

    logger.info("app_stopping", app_name=config.app_name)
    # Stop background services
    mwl_service.stop_auto_generation()
    scp_service.stop()


app = FastAPI(
    title=config.app_name,
    version=config.app_version,
    description="FastAPI service for generating mock DICOM objects and serving DICOM SCP services.",
    lifespan=lifespan,
)

app.include_router(router)
app.include_router(mcp_router)


def main() -> None:
    """Run FastAPI server via Uvicorn."""
    logger.info(STARTUP_NOTICE)
    logger.info("starting_uvicorn_server", host=config.host, port=config.port)
    uvicorn.run(
        "dicom_py_mock_server.main:app",
        host=config.host,
        port=config.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
