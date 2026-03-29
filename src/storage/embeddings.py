import httpx
from src.config import settings


def generate_embedding(text: str) -> list[float]:
    """
    Génère un embedding avec Ollama (synchrone).
    À utiliser uniquement dans un contexte non-async (ex: init prototypes).
    """
    if not text or not text.strip():
        return []

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{settings.ollama_base_url}/api/embeddings",
                json={
                    "model": settings.ollama_embed_model,
                    "prompt": text.strip(),
                },
            )
            response.raise_for_status()
            return response.json().get("embedding", [])
    except Exception as e:
        print(f"Erreur embedding (sync): {e}")
        return []


async def generate_embedding_async(text: str) -> list[float]:
    """
    Génère un embedding avec Ollama (async).
    À utiliser dans les agents et pipelines async.
    """
    if not text or not text.strip():
        return []

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/embeddings",
                json={
                    "model": settings.ollama_embed_model,
                    "prompt": text.strip(),
                },
            )
            response.raise_for_status()
            return response.json().get("embedding", [])
    except Exception as e:
        print(f"Erreur embedding (async): {e}")
        return []


def build_company_text(
    name: str,
    country: str = "",
    sector: str = "",
    certifs: list[str] | None = None,
) -> str:
    """
    Construit un texte descriptif d'entreprise pour l'embedding.
    """
    certifs = certifs or []
    parts = [name, "entreprise", country]
    if sector:
        parts.append(f"secteur {sector}")
    if certifs:
        parts.append(f"certifications {' '.join(certifs)}")
    return " ".join(p for p in parts if p)