import json
import uuid
from fastapi import APIRouter, HTTPException
from azure.cosmos.exceptions import CosmosHttpResponseError
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from .models_jobs import JobCreateRequest, job_to_entity, JobCreateResponse
from .cosmos import get_cosmos_container
from .blob_service import generate_url_upload_sas
from .config import settings

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


@router.post("/{jobId}/retry", status_code=200, summary="Retry a job", description="Republish a job message to Service Bus for reprocessing.")
def retry_job(jobId: str):
    container = get_cosmos_container()
    try:
        item = container.read_item(item=jobId, partition_key="JOB")
    except CosmosHttpResponseError as e:
        if getattr(e, 'status_code', None) == 404:
            raise HTTPException(status_code=404, detail="Job not found")
        raise HTTPException(status_code=500, detail=f"Cosmos error: {getattr(e, 'message', str(e))}")

    message_body = json.dumps({
        "documentId": jobId,
        "fileName": item.get("fileName", ""),
        "correlationId": str(uuid.uuid4()),
    })

    try:
        with ServiceBusClient.from_connection_string(settings.service_bus_connection_string) as sb_client:
            with sb_client.get_queue_sender(settings.service_bus_queue_name) as sender:
                sender.send_messages(ServiceBusMessage(message_body))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Service Bus error: {str(e)}")

    return {"jobId": jobId, "status": "requeued"}