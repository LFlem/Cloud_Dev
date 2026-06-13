# Cloud_Dev — Pipeline de traitement de documents IA sur Azure

![Deploy API](https://github.com/LFlem/Cloud_Dev/actions/workflows/api-build-push.yml/badge.svg)
![Deploy Functions](https://github.com/LFlem/Cloud_Dev/actions/workflows/main_myiotappcode.yml/badge.svg)
![Deploy Web](https://github.com/LFlem/Cloud_Dev/actions/workflows/deploy-web.yml/badge.svg)

Pipeline cloud événementiel qui prend un fichier uploadé par un utilisateur, le traite via une IA (tagging), et notifie l'interface en temps réel via Azure SignalR.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        React (cloudfront)                       │
│          Upload fichier → affichage statut temps réel           │
└────────────────────────┬──────────────────┬────────────────────-┘
                         │ POST /jobs        │ SignalR (WebSocket)
                         ▼                  ▼
               ┌─────────────────┐   ┌──────────────────┐
               │  API FastAPI    │   │  Azure SignalR   │
               │  mon-iot-api    │   │   iot-signalr    │
               └────────┬────────┘   └────────▲─────────┘
                        │ SAS URL             │ notifications
                        │                     │
                        ▼                     │
               ┌─────────────────┐   ┌────────┴─────────────────────┐
               │  Blob Storage   │   │     Azure Functions           │
               │  myiotstock     │   │     myiotappcode              │
               │  container:jobs │   │                               │
               └────────┬────────┘   │  1. BlobTriggerWorkerUp1     │
                        │ PUT file   │     → UPLOADED → QUEUED      │
                        │ (SAS)      │                               │
                        └───────────►│  2. ServiceBusProcessing      │
                                     │     → PROCESSING → PROCESSED  │
                       ┌─────────────│     (OpenAI tagging)          │
                       │             │                               │
               ┌───────▼───────┐     │  3. DLQAlertFunction         │
               │  Service Bus  │     │     → ERROR                  │
               │  my-iot       │     └───────────┬───────────────────┘
               │  queue:       │                 │
               │  document-    │                 │ read/write
               │  processing   │                 ▼
               └───────────────┘       ┌─────────────────┐
                   DLQ (3 retries)     │   CosmosDB      │
                                       │   mydbhanim     │
                                       │   db-docu/jobs  │
                                       └─────────────────┘
```

---

## Stack technique

| Composant | Technologie | Service Azure |
|---|---|---|
| API REST | FastAPI + Python 3.13 | App Service `mon-iot-api` |
| Functions | Azure Functions Python v2 | Function App `myiotappcode` |
| Frontend | React 19 + Vite | App Service `cloudfront` |
| Base de données | Azure CosmosDB (NoSQL) | `mydbhanim` / `db-docu` |
| Stockage fichiers | Azure Blob Storage | `myiotstock` / `jobs` |
| Messaging | Azure Service Bus | `my-iot` / `document-processing` |
| Temps réel | Azure SignalR Service | `iot-signalr` (mode Serverless) |
| Registry images | Azure Container Registry | `moniotacr` |
| Tagging IA | OpenAI API (gpt-3.5-turbo) | — |

---

## Pipeline métier

```
CREATED ──► UPLOADED ──► QUEUED ──► PROCESSING ──► PROCESSED
                                         │
                                         └──► ERROR (DLQ après 3 retries)
```

| Statut | Déclenché par | Action |
|---|---|---|
| `CREATED` | `POST /jobs` | Création du document en CosmosDB |
| `UPLOADED` | BlobTrigger | Fichier reçu dans Blob Storage |
| `QUEUED` | BlobTrigger | Message envoyé dans Service Bus |
| `PROCESSING` | ServiceBusFunction | Tagging IA en cours |
| `PROCESSED` | ServiceBusFunction | Tags générés, document mis à jour |
| `ERROR` | DLQAlertFunction | Échec après 3 retries |

---

## Structure du repo

```
src/
├── api/                          # FastAPI
│   ├── app/
│   │   ├── main.py               # App + CORS
│   │   ├── routes_jobs.py        # POST /jobs, GET /jobs/{id}, POST /jobs/{id}/retry
│   │   ├── models_jobs.py        # Modèles Pydantic
│   │   ├── config.py             # Variables d'environnement (pydantic-settings)
│   │   ├── cosmos.py             # Client CosmosDB
│   │   └── blob_service.py       # Génération SAS tokens
│   ├── Dockerfile
│   └── requirements.txt
├── functions/                    # Azure Functions Python v2
│   ├── function_app.py           # 4 functions (negotiate + 3 triggers)
│   ├── host.json
│   └── requirements.txt
└── web/                          # React + Vite
    ├── src/
    │   ├── App.jsx               # Upload + SignalR + pipeline statuts
    │   └── App.css
    ├── Dockerfile                # Multi-stage: node build + nginx
    ├── nginx.conf
    └── .env.example
.github/workflows/
├── api-build-push.yml            # CI/CD API → ACR → App Service
├── main_myiotappcode.yml         # CI/CD Functions
└── deploy-web.yml                # CI/CD React → ACR → App Service
```

---

## Déploiement

### Prérequis Azure

1. Resource Group avec les services listés dans le tableau de stack
2. Azure Container Registry `moniotacr` avec Admin enabled
3. Service Bus queue `document-processing` avec **Max delivery count = 3** et DLQ activée
4. SignalR Service `iot-signalr` en mode **Serverless**
5. Blob Storage CORS configuré pour autoriser l'origine de la web app (méthodes : PUT, GET, HEAD, OPTIONS)

### GitHub Secrets à configurer

```
ACR_LOGIN_SERVER          moniotacr.azurecr.io
ACR_USERNAME              moniotacr
ACR_PASSWORD              <mot de passe ACR>
AZURE_APP_NAME            mon-iot-api
AZURE_PUBLISH_PROFILE     <publish profile API App Service>
AZURE_FUNCTION_APP_NAME   myiotappcode
AZURE_FUNCTION_PUBLISH_PROFILE  <publish profile Function App>
AZURE_WEBAPP_PUBLISH_PROFILE    <publish profile Web App>
AZUREAPPSERVICE_CLIENTID_*      <OIDC client ID>
AZUREAPPSERVICE_TENANTID_*      <OIDC tenant ID>
AZUREAPPSERVICE_SUBSCRIPTIONID_* <OIDC subscription ID>
```

### Variables d'environnement Azure App Settings

**API (`mon-iot-api`) :**
```
COSMOS_ENDPOINT                  https://mydbhanim.documents.azure.com:443/
COSMOS_KEY                       <clé CosmosDB>
COSMOS_DATABASE                  db-docu
COSMOS_CONTAINER                 jobs
BLOB_CONNECTION_STRING           <connection string Storage Account>
SERVICE_BUS_CONNECTION_STRING    Endpoint=sb://my-iot.servicebus.windows.net/;...
SERVICE_BUS_QUEUE_NAME           document-processing
```

**Function App (`myiotappcode`) :**
```
myiotstock_STORAGE               <connection string Storage Account>
SERVICE_BUS_CONNECTION_STRING    Endpoint=sb://my-iot.servicebus.windows.net/;...
SERVICE_BUS_QUEUE_NAME           document-processing
COSMOS_ENDPOINT                  https://mydbhanim.documents.azure.com:443/
COSMOS_KEY                       <clé CosmosDB>
COSMOS_DATABASE                  db-docu
COSMOS_CONTAINER                 jobs
AzureSignalRConnectionString     Endpoint=https://iot-signalr.service.signalr.net;...
OPENAI_API_KEY                   <optionnel — active le tagging IA>
```

---

## Développement local

### API
```bash
cd src/api
cp .env.example .env   # remplir les valeurs
pip install -r requirements.txt
uvicorn app.main:app --reload   # http://localhost:8000/docs
```

### Azure Functions
```bash
cd src/functions
pip install -r requirements.txt
# Créer local.settings.json avec les variables ci-dessus
func start
```

### React
```bash
cd src/web
npm install
npm run dev   # http://localhost:5173
```

---

## Test end-to-end

1. Ouvrir la web app (`cloudfront.azurewebsites.net`)
2. Renseigner l'URL de l'API et l'URL du Function App
3. Sélectionner un fichier et cliquer **Créer le job + uploader**
4. Observer la progression en temps réel : `CREATED → UPLOADED → QUEUED → PROCESSING → PROCESSED`
5. Les tags IA générés apparaissent automatiquement à la fin du traitement

Pour tester le retry (DLQ) :
```
POST /jobs/{jobId}/retry
```
Republier un message dans Service Bus depuis l'interface Swagger (`/docs`).

---

## Endpoints API

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/health` | Vérification de santé |
| `POST` | `/jobs` | Créer un job + obtenir l'URL SAS d'upload |
| `GET` | `/jobs/{jobId}` | Lire l'état d'un job |
| `POST` | `/jobs/{jobId}/retry` | Republier un job dans Service Bus |

---

## Observabilité

Tous les logs sont structurés en JSON avec `correlationId` et `documentId` à chaque étape :

```json
{
  "correlationId": "abc-123",
  "documentId": "uuid",
  "step": "AI_TAGGING",
  "status": "SUCCESS",
  "tags": ["cv", "azure", "cloud"]
}
```

Consultables via : **Azure Portal → Function App → Monitoring → Log stream**
