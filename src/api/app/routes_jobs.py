from fastapi import APIRouter, HTTPException
from azure.cosmos.exceptions import CosmosHttpResponseError
from .models_jobs import JobCreateRequest, job_to_entity, JobCreateResponse
from .cosmos import get_cosmos_container
from .blob_service import generate_url_upload_sas

router = APIRouter(prefix="/jobs", tags=["jobs"])

@router.post("", status_code=201, summary="Create a new job", description="Create a new job with the provided details.")
def create_job(req: JobCreateRequest):
    container = get_cosmos_container()
    entity = job_to_entity(req)

    try:
        container.create_item(body=entity)
    except CosmosHttpResponseError as e:
        raise HTTPException(status_code=500, detail=f"Cosmos error: {getattr(e, 'message', str(e))}")
    
    blob_path = f"{entity['id']}/{req.fileName}"
    upload_url = generate_url_upload_sas(blob_path)
    return JobCreateResponse(
        jobId=entity["id"],
        status=entity["status"],
        createdAt=entity["createdAt"],
        category=entity["category"],
        uploadUrl=upload_url
    )

@router.get("/{jobId}", status_code=200, summary="Get a job", description="Retrieve details of a specific job.")
def get_jobs(jobId: str):
    container = get_cosmos_container()
    try:
        item = container.read_item(item=jobId, partition_key="JOB")
        return item
    except CosmosHttpResponseError as e:
        if getattr(e, 'status_code', None) == 404:
            raise HTTPException(status_code=404, detail="Job not found")
        raise HTTPException(status_code=500, detail=f"Cosmos error: {getattr(e, 'message', str(e))}")