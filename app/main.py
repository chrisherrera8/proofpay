from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import cleaner, jobs, paypal
from app.config import get_settings
from app.state_machine import InvalidTransition
from app.vision import VisionError

app = FastAPI(title="ProofPay")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(jobs.router)
app.include_router(paypal.router)
app.include_router(cleaner.router)


@app.exception_handler(InvalidTransition)
def _invalid_transition(_: Request, exc: InvalidTransition) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(VisionError)
def _vision_error(_: Request, exc: VisionError) -> JSONResponse:
    # Raised when the provider can't even be built (e.g. no API key); runtime failures are handled in the route.
    return JSONResponse(status_code=503, content={"detail": f"Vision check unavailable: {exc}"})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
