from fastapi import APIRouter

from app.api.v1.endpoints import auth, health, organizations, websites

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(websites.router)
