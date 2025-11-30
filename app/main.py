# app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# These two are not strictly needed anymore in main, but ok to keep
from app.db.session import engine
from app.db.base import Base

# ✅ This is our new init that does create_all + tiny migration
from app.db.init_db import init_db

from app.api.v1.users import router as users_router
from app.api.v1.chat import router as chat_router
from app.api.v1.plans import router as plans_router
from app.api.v1.billing import router as billing_router
from app.api.v1.watchlist import router as watchlist_router
from app.api.v1.memberships import router as memberships_router

app = FastAPI(title="Kartquake")

# CORS so frontend (Vite at 5173) can talk to backend (8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Single startup hook – calls init_db (which internally does Base.metadata.create_all)
@app.on_event("startup")
def on_startup() -> None:
    init_db()
    print("✅ Database tables created (if not existed)")
    print("🚀 Kartquake backend initialized")


app.include_router(users_router)
app.include_router(chat_router)
app.include_router(plans_router)
app.include_router(billing_router)
app.include_router(watchlist_router)
app.include_router(memberships_router)


@app.get("/")
def root():
    return {"message": "Kartquake backend is running"}
