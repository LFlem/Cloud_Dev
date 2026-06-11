import azure.functions as func
import logging
import json
import os
import uuid
from datetime import datetime, timezone

from azure.cosmos import CosmosClient
from azure.servicebus import ServiceBusClient, ServiceBusMessage

app = func.FunctionApp()

# Config
COSMOS_ENDPOINT = os.environ["COSMOS_ENDPOINT"]
COSMOS_KEY = os.environ["COSMOS_KEY"]
COSMOS_DATABASE = os.environ["COSMOS_DATABASE"]
COSMOS_CONTAINER = os.environ["COSMOS_CONTAINER"]
SERVICE_BUS_CONNECTION = os.environ["SERVICE_BUS_CONNECTION_STRING"]
SERVICE_BUS_QUEUE = os.environ["SERVICE_BUS_QUEUE_NAME"]

def get_cosmos_container():
    client = CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)
    db = client.get_database_client(COSMOS_DATABASE)
    return db.get_container_client(COSMOS_CONTAINER)

def update_document_status(document_id: str, status: str, extra: dict = {}):
    container = get_cosmos_container()
    patch_ops = [
        {"op": "replace", "path": "/status", "value": status},
        {"op": "replace", "path": "/updatedAt", "value": datetime.now(timezone.utc).isoformat()},
    ]
    for key, value in extra.items():
        patch_ops.append({"op": "add", "path": f"/{key}", "value": value})
    try:
        container.patch_item(item=document_id, partition_key=document_id, patch_operations=patch_ops)
    except Exception:
        doc = container.read_item(item=document_id, partition_key=document_id)
        doc["status"] = status
        doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
        doc.update(extra)
        container.upsert_item(doc)

def generate_tags_fallback(file_name: str) -> list:
    name = file_name.lower().replace("_", " ").replace("-", " ").replace(".", " ")
    words = [w for w in name.split() if len(w) > 2 and w not in ["the", "and", "for", "les", "des", "une", "par"]]
    tags = list(set(words))[:8]
    if "pdf" in name: tags.append("pdf")
    if "cv" in name or "resume" in name: tags.extend(["cv", "rh"])
    return list(set(tags))[:8]

def generate_tags_ai(file_name: str) -> list:
    try:
        import requests
        openai_key = os.environ.get("OPENAI_API_KEY")
        if not openai_key:
            return generate_tags_fallback(file_name)
        prompt = f"""Analyse le nom de fichier suivant et génère entre 3 et 8 tags courts en français.
Nom du fichier : {file_name}
Retourne uniquement un tableau JSON de chaînes, sans explication."""
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
            json={"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": prompt}], "max_tokens": 100},
            timeout=10
        )
        content = response.json()["choices"][0]["message"]["content"].strip()
        tags = json.loads(content)
        if isinstance(tags, list):
            return tags[:8]
    except Exception as e:
        logging.warning(f"AI tagging failed, using fallback: {e}")
    return generate_tags_fallback(file_name)


# ─── FUNCTION 1 : Blob Trigger ───────────────────────────────────────────────

@app.blob_trigger(arg_name="myblob", path="jobs/{name}",
                  connection="myiotstock_STORAGE")
def BlobTriggerWorkerUp1(myblob: func.InputStream):
    correlation_id = str(uuid.uuid4())
    blob_name = myblob.name
    file_name = blob_name.split("/")[-1]
    size = myblob.length

    logging.info(json.dumps({
        "correlationId": correlation_id,
        "step": "BLOB_TRIGGER",
        "blobName": blob_name,
        "size": size,
        "status": "RECEIVED"
    }))

    # Extraire documentId depuis le nom du blob (format: documentId_fileName)
    parts = file_name.split("_", 1)
    document_id = parts[0] if len(parts) > 1 else file_name

    try:
        # Mettre à jour le statut CosmosDB → UPLOADED
        update_document_status(document_id, "UPLOADED")

        # Publier message dans Service Bus
        message_body = json.dumps({
            "documentId": document_id,
            "fileName": file_name,
            "blobName": blob_name,
            "size": size,
            "uploadedAt": datetime.now(timezone.utc).isoformat(),
            "correlationId": correlation_id
        })

        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            with sb_client.get_queue_sender(SERVICE_BUS_QUEUE) as sender:
                sender.send_messages(ServiceBusMessage(message_body))

        # Mettre à jour → QUEUED
        update_document_status(document_id, "QUEUED")

        logging.info(json.dumps({
            "correlationId": correlation_id,
            "documentId": document_id,
            "step": "BLOB_TRIGGER",
            "status": "SUCCESS",
            "message": "Message publié dans Service Bus"
        }))

    except Exception as e:
        logging.error(json.dumps({
            "correlationId": correlation_id,
            "documentId": document_id,
            "step": "BLOB_TRIGGER",
            "status": "ERROR",
            "error": str(e)
        }))
        update_document_status(document_id, "ERROR", {"errorMessage": str(e)})


# ─── FUNCTION 2 : Service Bus Processing ─────────────────────────────────────

@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%SERVICE_BUS_QUEUE_NAME%",
    connection="SERVICE_BUS_CONNECTION_STRING"
)
def ServiceBusProcessingFunction(msg: func.ServiceBusMessage):
    correlation_id = str(uuid.uuid4())
    body = msg.get_body().decode("utf-8")

    try:
        data = json.loads(body)
        document_id = data["documentId"]
        file_name = data["fileName"]
        correlation_id = data.get("correlationId", correlation_id)

        logging.info(json.dumps({
            "correlationId": correlation_id,
            "documentId": document_id,
            "step": "SERVICE_BUS_PROCESSING",
            "status": "STARTED"
        }))

        # → PROCESSING
        update_document_status(document_id, "PROCESSING")

        # Tagging IA
        logging.info(json.dumps({
            "correlationId": correlation_id,
            "documentId": document_id,
            "step": "AI_TAGGING",
            "status": "STARTED"
        }))

        tags = generate_tags_ai(file_name)

        logging.info(json.dumps({
            "correlationId": correlation_id,
            "documentId": document_id,
            "step": "AI_TAGGING",
            "status": "SUCCESS",
            "tags": tags
        }))

        # → PROCESSED
        update_document_status(document_id, "PROCESSED", {
            "tags": tags,
            "processedAt": datetime.now(timezone.utc).isoformat()
        })

        logging.info(json.dumps({
            "correlationId": correlation_id,
            "documentId": document_id,
            "step": "SERVICE_BUS_PROCESSING",
            "status": "SUCCESS"
        }))

    except KeyError as e:
        logging.error(json.dumps({
            "correlationId": correlation_id,
            "step": "SERVICE_BUS_PROCESSING",
            "status": "ERROR",
            "error": f"Message mal formé: {str(e)}"
        }))
        raise  # → DLQ après max retries

    except Exception as e:
        logging.error(json.dumps({
            "correlationId": correlation_id,
            "step": "SERVICE_BUS_PROCESSING",
            "status": "ERROR",
            "error": str(e)
        }))
        raise  # → DLQ après max retries


# ─── FUNCTION 3 : DLQ Alert ──────────────────────────────────────────────────

@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="%SERVICE_BUS_QUEUE_NAME%/$deadletterqueue",
    connection="SERVICE_BUS_CONNECTION_STRING"
)
def DLQAlertFunction(msg: func.ServiceBusMessage):
    correlation_id = str(uuid.uuid4())
    body = msg.get_body().decode("utf-8")

    logging.error(json.dumps({
        "correlationId": correlation_id,
        "step": "DLQ_ALERT",
        "status": "MESSAGE_IN_DLQ",
        "body": body
    }))

    try:
        data = json.loads(body)
        document_id = data.get("documentId")

        if document_id:
            update_document_status(document_id, "ERROR", {
                "errorMessage": "Message envoyé en DLQ après plusieurs échecs",
                "errorAt": datetime.now(timezone.utc).isoformat(),
                "dlqBody": body[:500]
            })

            logging.error(json.dumps({
                "correlationId": correlation_id,
                "documentId": document_id,
                "step": "DLQ_ALERT",
                "status": "COSMOS_UPDATED"
            }))

    except Exception as e:
        logging.error(json.dumps({
            "correlationId": correlation_id,
            "step": "DLQ_ALERT",
            "status": "ERROR",
            "error": str(e)
        }))