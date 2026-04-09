from azure.cosmos import CosmosClient, PartitionKey
from .config import settings

_client: CosmosClient | None = None

def get_cosmos_container():
    global _client
    if _client is None:
        _client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)

    # Ensure required Cosmos resources exist before returning the container.
    db = _client.create_database_if_not_exists(id=settings.cosmos_database)
    container = db.create_container_if_not_exists(
        id=settings.cosmos_container,
        partition_key=PartitionKey(path="/pk"),
    )
    return container
