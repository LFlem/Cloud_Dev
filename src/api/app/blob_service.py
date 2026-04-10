from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.exceptions import ResourceExistsError
from datetime import datetime, timedelta
from .config import settings

blob_service = BlobServiceClient.from_connection_string(settings.blob_connection_string)
account_key = blob_service.credential.account_key

try:
    blob_service.create_container(settings.blob_container_name)
except ResourceExistsError:
    pass

def generate_url_upload_sas(blob_name: str):
    sas_token = generate_blob_sas(
        account_name=blob_service.account_name,
        container_name=settings.blob_container_name,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True, write=True, create=True),
        start=datetime.utcnow() - timedelta(minutes=5),
        expiry=datetime.utcnow() + timedelta(minutes=30),
    )
    return f"https://{blob_service.account_name}.blob.core.windows.net/{settings.blob_container_name}/{blob_name}?{sas_token}"