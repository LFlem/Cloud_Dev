import azure.functions as func
import logging
import json
import os
import uuid
import hmac
import hashlib
import base64
import time
from urllib.parse import quote
from datetime import datetime, timezone

import requests as http_requests
from azure.cosmos import CosmosClient
from azure.servicebus import ServiceBusClient, ServiceBusMessage

app = func.FunctionApp()


def get_config():
    return {
        "COSMOS_ENDPOINT": os.environ["COSMOS_ENDPOINT"],
        "COSMOS_KEY": os.environ["COSMOS_KEY"],
        "COSMOS_DATABASE": os.environ["COSMOS_DATABASE"],
        "COSMOS_CONTAINER": os.environ["COSMOS_CONTAINER"],
        "SERVICE_BUS_CONNECTION": os.environ["SERVICE_BUS_CONNECTION_STRING"],
        "SERVICE_BUS_QUEUE": os.environ["SERVICE_BUS_QUEUE_NAME"],
    }


def get_cosmos_container():
    cfg = get_config()
    client = CosmosClient(cfg["COSMOS_ENDPOINT"], cfg["COSMOS_KEY"])
    db = client.get_database_client(cfg["COSMOS_DATABASE"])
    return db.get_container_client(cfg["COSMOS_CONTAINER"])


def update_document_status(document_id: str, status: str, extra: dict = {}):
    container = get_cosmos_container()
    patch_ops = [
        {"op": "replace", "path": "/status", "value": status},
        {"op": "replace", "path": "/updatedAt", "value": datetime.now(timezone.utc).isoformat()},
    ]
    for key, value in extra.items():
        patch_ops.append({"op": "add", "path": f"/{key}", "value": value})
    try:
        container.patch_item(item=document_id, partition_key="JOB", patch_operations=patch_ops)
    except Exception:
        doc = container.read_item(item=document_id, partition_key="JOB")
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


# ─── SignalR helpers ──────────────────────────────────────────────────────────

def _parse_signalr_connection(conn_str: str) -> tuple:
    parts = dict(p.split("=", 1) for p in conn_str.rstrip(";").split(";") if "=" in p)
    return parts.get("Endpoint", "").rstrip("/"), parts.get("AccessKey", "")


def _signalr_jwt(audience: str, access_key: str, ttl: int = 60) -> str:
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps({"aud": audience, "exp": int(time.time()) + ttl}).encode()
    ).rstrip(b"=").decode()
    sig_input = f"{header}.{payload}".encode()
    sig = base64.urlsafe_b64encode(
        hmac.new(access_key.encode(), sig_input, hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.{sig}"


def send_signalr_notification(payload: dict, hub: str = "notifications") -> None:
    conn_str = os.environ.get("AzureSignalRConnectionString", "")
    if not conn_str:
        return
    endpoint, key = _parse_signalr_connection(conn_str)
    audience = f"{endpoint}/api/v1/hubs/{hub}"
    token = _signalr_jwt(audience, key)
    try:
        http_requests.post(
            audience,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"target": "statusUpdate", "arguments": [payload]},
            timeout=5,
        )
    except Exception as e:
        logging.warning(f"SignalR notification failed: {e}")


# ─── FUNCTION 0 : SignalR Negotiate ──────────────────────────────────────────

@app.route(route="negotiate", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def negotiate(req: func.HttpRequest) -> func.HttpResponse:
    conn_str = os.environ.get("AzureSignalRConnectionString", "")
    if not conn_str:
        return func.HttpResponse("AzureSignalRConnectionString not configured", status_code=500)
    endpoint, key = _parse_signalr_connection(conn_str)
    hub = "notifications"
    client_url = f"{endpoint}/client/?hub={hub}"
    token = _signalr_jwt(client_url, key, ttl=3600)
    return func.HttpResponse(
        json.dumps({"url": client_url, "accessToken": token}),
        mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )


# ─── FUNCTION 1 : Blob Trigger ───────────────────────────────────────────────

@app.blob_trigger(arg_name="myblob", path="jobs/{name}",
                  connection="myiotstock_STORAGE")
def BlobTriggerWorkerUp1(myblob: func.InputStream):
    cfg = get_config()
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

    # jobId is the path segment between container name and filename: jobs/{jobId}/{filename}
    document_id = blob_name.split("/")[-2]

    try:
        update_document_status(document_id, "UPLOADED")

        message_body = json.dumps({
            "documentId": document_id,
            "fileName": file_name,
            "blobName": blob_name,
            "size": size,
            "uploadedAt": datetime.now(timezone.utc).isoformat(),
            "correlationId": correlation_id
        })

        with ServiceBusClient.from_connection_string(cfg["SERVICE_BUS_CONNECTION"]) as sb_client:
            with sb_client.get_queue_sender(cfg["SERVICE_BUS_QUEUE"]) as sender:
                sender.send_messages(ServiceBusMessage(message_body))

        update_document_status(document_id, "QUEUED")
        send_signalr_notification({"documentId": document_id, "status": "QUEUED", "message": "Fichier reçu, en attente de traitement"})

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
        send_signalr_notification({"documentId": document_id, "status": "ERROR", "message": str(e)})


# ─── FUNCTION 2 : Service Bus Processing ─────────────────────────────────────

@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="document-processing",
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

        update_document_status(document_id, "PROCESSING")
        send_signalr_notification({"documentId": document_id, "status": "PROCESSING", "message": "Traitement IA en cours"})

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

        update_document_status(document_id, "PROCESSED", {
            "tags": tags,
            "processedAt": datetime.now(timezone.utc).isoformat()
        })
        send_signalr_notification({"documentId": document_id, "status": "PROCESSED", "message": "Tagging terminé", "tags": tags})

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
        raise

    except Exception as e:
        logging.error(json.dumps({
            "correlationId": correlation_id,
            "step": "SERVICE_BUS_PROCESSING",
            "status": "ERROR",
            "error": str(e)
        }))
        raise


# ─── FUNCTION 3 : DLQ Alert ──────────────────────────────────────────────────

@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="document-processing/$deadletterqueue",
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
            send_signalr_notification({"documentId": document_id, "status": "ERROR", "message": "Erreur de traitement — message en DLQ"})

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