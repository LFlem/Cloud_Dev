from pydantic import BaseModel, Field
from typing import Dict, Any
import uuid
from datetime import datetime, timezone

class JobCreateRequest(BaseModel):
    fileName: str = Field(..., min_length=3)
    contentType: str = Field(default="application/octet_stream")


class JobCreateResponse(BaseModel):
    jobId: str
    status: str
    createdAt: str
    category: str

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def job_to_entity(req: JobCreateRequest) -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    ts = now_iso()
    return {
        "id": job_id,
        "pk": "JOB",
        "resultSummary": None,
        "error": None,
        "createdAt": ts,
        "updatedAt": ts,
        "fileName": req.fileName,
        "contentType": req.contentType,
        "status": "CREATED",
        "category": ""
    }