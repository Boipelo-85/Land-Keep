"""LandKeep API.  Run:  uvicorn app.main:app --reload   (docs at http://localhost:8000/docs)"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401  (registers the tables)
from .database import Base, engine
from .routers import applications, auth, leases, maintenance, units

app = FastAPI(title="LandKeep API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(engine)

app.include_router(auth.router)
app.include_router(units.router)
app.include_router(applications.router)
app.include_router(leases.router)
app.include_router(maintenance.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
