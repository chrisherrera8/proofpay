from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import jobs
from app.state_machine import InvalidTransition

app = FastAPI(title="ProofPay")
app.include_router(jobs.router)


@app.exception_handler(InvalidTransition)
def _invalid_transition(_: Request, exc: InvalidTransition) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
