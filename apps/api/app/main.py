import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.deployment import deployment_problems
from app.logging_config import configure_logging

configure_logging()
settings = get_settings()
for _problem in deployment_problems(settings):
    logging.getLogger("rankpilot.deployment").warning("deployment %s [%s]: %s", _problem["level"], _problem["code"], _problem["message"])

app = FastAPI(title="RankPilot AI API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api/v1")
