"""Version 1 of the PENUMBRA API."""

from fastapi import APIRouter

from .endpoints import admin, advisor, auth, chat, portfolio, results

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(portfolio.router, prefix="/portfolio", tags=["portfolio"])
api_router.include_router(advisor.router, prefix="/advisor", tags=["advisor"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(results.router, prefix="/results", tags=["results"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])

__all__ = ["api_router"]
