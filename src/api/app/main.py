from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes_jobs import router as jobs_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"https://.*\.azurewebsites\.net",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)

@app.get("/health")
def health():
    return {"status": "ok"}