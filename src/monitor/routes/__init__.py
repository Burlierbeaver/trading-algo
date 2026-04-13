from monitor.routes.api import router as api_router
from monitor.routes.events import router as events_router
from monitor.routes.pages import router as pages_router

__all__ = ["api_router", "events_router", "pages_router"]
