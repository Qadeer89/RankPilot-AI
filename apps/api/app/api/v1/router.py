from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin_knowledge,
    ai_agents,
    analytics,
    auth,
    chat,
    crawls,
    deploy_webhook,
    execution,
    health,
    onboarding,
    opportunities,
    organizations,
    reporting,
    search_console,
    websites,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(websites.router)
api_router.include_router(crawls.router)
api_router.include_router(deploy_webhook.router)
api_router.include_router(search_console.router)
api_router.include_router(analytics.router)
api_router.include_router(opportunities.router)
api_router.include_router(execution.router)
api_router.include_router(reporting.router)
api_router.include_router(ai_agents.router)
api_router.include_router(onboarding.router)
api_router.include_router(chat.router)
api_router.include_router(admin_knowledge.router)
