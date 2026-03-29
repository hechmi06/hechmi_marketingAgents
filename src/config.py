from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral"
    ollama_embed_model: str = "nomic-embed-text"

    request_delay_seconds: int = 2
    pappers_api_key: str = ""

    embedding_confidence_threshold: float = 0.65  
    llm_confidence_threshold: float = 0.50

    class Config:
        env_file = ".env"


settings = Settings()