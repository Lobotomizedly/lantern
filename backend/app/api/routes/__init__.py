"""
Lantern API Routes
Export all routers for registration in main application.
"""

from app.api.routes.auth import router as auth_router
from app.api.routes.subjects import router as subjects_router
from app.api.routes.search import router as search_router
from app.api.routes.narratives import router as narratives_router
from app.api.routes.timeline import router as timeline_router
from app.api.routes.agents import router as agents_router
from app.api.routes.artifacts import router as artifacts_router
from app.api.routes.reviews import router as reviews_router
from app.api.routes.items import router as items_router
from app.api.routes.events import router as events_router
from app.api.routes.dashboard import router as dashboard_router

__all__ = [
    "auth_router",
    "subjects_router",
    "search_router",
    "narratives_router",
    "timeline_router",
    "agents_router",
    "artifacts_router",
    "reviews_router",
    "items_router",
    "events_router",
    "dashboard_router",
]
