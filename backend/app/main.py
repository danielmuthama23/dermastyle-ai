import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agent.workflow import InvalidTransition
from .api.routes import router
from .config import get_settings
from .deps import get_youcam

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await get_youcam().aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="DermaStyle AI", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )

    @app.exception_handler(InvalidTransition)
    async def _bad_transition(_: Request, exc: InvalidTransition):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    app.include_router(router)
    return app


app = create_app()
