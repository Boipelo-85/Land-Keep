from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import applications, auth, leases, units

app = FastAPI(title="Land-Keep API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(units.router)
app.include_router(applications.router)
app.include_router(leases.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
