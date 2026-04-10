# CI/CD Setup Guide pour Azure Web App

## Prérequis

1. **GitHub Repository** : Votre code est sur GitHub
2. **Azure Account** : Avec accès à Azure Web App
3. **Container Registry** : GitHub Container Registry (GHCR) activé

## Architecture

```
GitHub Push → GitHub Actions → Docker Build → GHCR → Azure Web App Deploy
```

## Étapes de mise en place

### 1. Créer deux Web Apps sur Azure

#### Frontend Web App
```bash
# Créer le groupe de ressources
az group create --name rg-ynov-cloud --location spaincentral

# Créer l'App Service Plan
az appservice plan create \
  --name asp-ynov-web \
  --resource-group rg-ynov-cloud \
  --sku B1 \
  --is-linux

# Créer la Web App pour le frontend
az webapp create \
  --resource-group rg-ynov-cloud \
  --plan asp-ynov-web \
  --name mon-iot-app-web \
  --deployment-container-image-name "ghcr.io/your-username/your-repo/web:latest"
```

#### API Web App
```bash
# Créer l'App Service Plan pour l'API
az appservice plan create \
  --name asp-ynov-api \
  --resource-group rg-ynov-cloud \
  --sku B1 \
  --is-linux

# Créer la Web App pour l'API
az webapp create \
  --resource-group rg-ynov-cloud \
  --plan asp-ynov-api \
  --name mon-iot-api \
  --deployment-container-image-name "ghcr.io/your-username/your-repo/api:latest"
```

### 2. Configurer l'authentification GHCR pour Azure

```bash
# Créer un Personal Access Token (PAT) sur GitHub :
# 1. Aller sur https://github.com/settings/tokens
# 2. Cliquer "Generate new token (classic)"
# 3. Sélectionner scopes : repo, write:packages, read:packages
# 4. Copier le token

# Configurer l'authentification pour chaque Web App
az webapp config container set \
  --name mon-iot-app-web \
  --resource-group rg-ynov-cloud \
  --docker-custom-image-name "ghcr.io/your-username/your-repo/web:latest" \
  --docker-registry-server-url "https://ghcr.io" \
  --docker-registry-server-user "your-username" \
  --docker-registry-server-password "your-pat-token"

az webapp config container set \
  --name mon-iot-api \
  --resource-group rg-ynov-cloud \
  --docker-custom-image-name "ghcr.io/your-username/your-repo/api:latest" \
  --docker-registry-server-url "https://ghcr.io" \
  --docker-registry-server-user "your-username" \
  --docker-registry-server-password "your-pat-token"
```

### 3. Ajouter les secrets GitHub

1. Aller sur votre repo GitHub → Settings → Secrets and variables → Actions
2. Ajouter :

```
AZURE_WEBAPP_PUBLISH_PROFILE : (copier depuis Azure Portal → Web App → Export Profile)
AZURE_WEBAPP_PUBLISH_PROFILE_API : (même chose pour l'API)
```

Pour exporter les profils :
- Azure Portal → Web App → Download publish profile
- Copier tout le contenu du fichier `.PublishSettings` dans le secret

### 4. Configurer les variables d'environnement

#### Frontend (.env.production)
```
VITE_API_BASE_URL=https://mon-iot-api.azurewebsites.net
```

#### API - Azure Portal
- Pour `mon-iot-api` Web App :
  - Settings → Configuration → Application Settings
  - Ajouter :
    ```
    COSMOS_ENDPOINT=votre-endpoint
    COSMOS_KEY=votre-clé
    COSMOS_DATABASE=db-docu
    COSMOS_CONTAINER=jobs
    BLOB_CONNECTION_STRING=votre-string
    ```

### 5. Tester le déploiement

```bash
# Push vers main pour déclencher le workflow
git add .
git commit -m "Setup CI/CD for Azure Web App"
git push origin main

# Vérifier le statut dans GitHub → Actions
```

### 6. Vérifier après déploiement

```bash
# Frontend
curl https://mon-iot-app-web.azurewebsites.net

# API
curl https://mon-iot-api.azurewebsites.net/health
```

## Troubleshooting

### Container ne démarre pas
```bash
# Voir les logs
az webapp log tail --resource-group rg-ynov-cloud --name mon-iot-api
```

### Erreur d'authentification GHCR
- Vérifier le PAT token (Settings → Tokens)
- Vérifier que l'utilisateur a accès à GHCR

### Problème CORS
- L'API doit retourner le header `Access-Control-Allow-Origin: https://mon-iot-app-web.azurewebsites.net`
- C'est déjà configuré dans `main.py` mais adapter si besoin l'URL

## Structure attendue après déploiement

```
GitHub
  └─ .github/workflows/
      ├─ deploy-web.yml     → Push → Build React → GHCR → Azure Web App (Frontend)
      └─ deploy-api.yml     → Push → Build FastAPI → GHCR → Azure Web App (API)
```
