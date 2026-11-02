from fastapi import APIRouter

from app.api.v1.endpoints import auth, crawls, execution, health, opportunities, organizations, search_console, websites

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(websites.router)
api_router.include_router(crawls.router)
api_router.include_router(search_console.router)
api_router.include_router(opportunities.router)
api_router.include_router(execution.router)
