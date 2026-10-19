<<<<<<< HEAD
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
=======
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import applications, auth, leases, notifications, units

app = FastAPI(title="Land-Keep API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
<<<<<<< HEAD

Base.metadata.create_all(engine)

=======
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
app.include_router(auth.router)
app.include_router(units.router)
app.include_router(applications.router)
app.include_router(leases.router)
<<<<<<< HEAD
app.include_router(maintenance.router)


@app.get("/health", tags=["meta"])
=======
app.include_router(notifications.router)


@app.get("/health", tags=["health"])
>>>>>>> 254c9b89f9d0f22a8e6cead7e0f8cab6807b63e3
def health():
    return {"status": "ok"}
