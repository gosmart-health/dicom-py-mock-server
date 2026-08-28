"""Main FastAPI application entry point for dicom-py-mock-server."""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from dicom_py_mock_server.api import mcp_router, router
from dicom_py_mock_server.config import config
from dicom_py_mock_server.logging_config import get_logger, setup_logging

# Initialize logging system
setup_logging(config)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event context manager for FastAPI application."""
    logger.info("app_starting", app_name=config.app_name, version=config.app_version)
    yield
    logger.info("app_stopping", app_name=config.app_name)


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
    logger.info("starting_uvicorn_server", host=config.host, port=config.port)
    uvicorn.run(
        "dicom_py_mock_server.main:app",
        host=config.host,
        port=config.port,
        reload=False,
    )


if __name__ == "__main__":
    main()

