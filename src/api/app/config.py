from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    cosmos_endpoint: str
    cosmos_key: str
    cosmos_database: str
    cosmos_container: str
    blob_connection_string: str
    blob_container_name: str = "jobs"
    service_bus_connection_string: str = ""
    service_bus_queue_name: str = "document-processing"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()