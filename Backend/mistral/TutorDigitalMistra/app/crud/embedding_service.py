"""
Servicio de Embeddings — Azure OpenAI text-embedding-3-small (1536 dims)
Reemplaza el embedding de Mistral. Incluye caché en PostgreSQL.
"""
import os
import hashlib
import time
import threading
import functools
from collections import defaultdict
from typing import List

from sqlalchemy.orm import Session
from openai import AzureOpenAI

from app.models.modelos import EmbeddingCache

# ============================================================================
# Configuración del Cliente Azure OpenAI
# ============================================================================

AZURE_OPENAI_KEY = os.getenv("OPENAI_API_KEY")
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "https://ia-mistral-recurso.cognitiveservices.azure.com/")
EMBEDDING_DEPLOYMENT = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = 1536  # Dimensión de text-embedding-3-small

if AZURE_OPENAI_KEY:
    openai_client = AzureOpenAI(
        api_version="2024-12-01-preview",
        azure_endpoint=AZURE_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
    )
else:
    openai_client = None

# ============================================================================
# Rate Limiter (para respetar límites de la API)
# ============================================================================

class RateLimiter:
    def __init__(self, max_requests: int = 50, time_window: float = 60.0):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)
        self.lock = threading.Lock()
    
    def wait_if_needed(self, key: str = "embed"):
        with self.lock:
            now = time.time()
            self.requests[key] = [ts for ts in self.requests[key] if now - ts < self.time_window]
            if len(self.requests[key]) >= self.max_requests:
                wait_time = self.time_window - (now - self.requests[key][0])
                if wait_time > 0:
                    time.sleep(wait_time)
            self.requests[key].append(time.time())

rate_limiter = RateLimiter()

# ============================================================================
# Retry con Backoff Exponencial
# ============================================================================

def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if ("429" in str(e) or "rate" in str(e).lower()) and attempt < max_retries - 1:
                        time.sleep(base_delay * (2 ** attempt))
                    elif attempt == max_retries - 1:
                        raise e
            return None
        return wrapper
    return decorator

# ============================================================================
# Funciones de Embedding
# ============================================================================

@retry_with_backoff()
def _generate_embedding_api(texto: str) -> List[float]:
    """Llama a la API de OpenAI para generar un embedding."""
    if not openai_client:
        return [0.0] * EMBEDDING_DIM
    
    rate_limiter.wait_if_needed("embed")
    
    # Limpiar texto (OpenAI recomienda reemplazar newlines)
    texto_limpio = texto.replace("\n", " ").strip()
    if not texto_limpio:
        return [0.0] * EMBEDDING_DIM
    
    response = openai_client.embeddings.create(
        model=EMBEDDING_DEPLOYMENT,
        input=[texto_limpio]
    )
    return response.data[0].embedding


def generar_embedding(db: Session, texto: str) -> List[float]:
    """
    Genera un embedding revisando caché primero.
    Si no existe en caché, llama a OpenAI text-embedding-3-small.
    """
    text_hash = hashlib.sha256(texto.encode('utf-8')).hexdigest()
    
    # Buscar en caché
    cached = db.query(EmbeddingCache).filter(
        EmbeddingCache.text_hash == text_hash
    ).first()
    
    if cached:
        return cached.embedding
    
    # Generar nuevo embedding via API
    vector = _generate_embedding_api(texto)
    
    # Cachear resultado
    try:
        db.add(EmbeddingCache(
            text_hash=text_hash,
            original_text=texto[:2000],  # Limitar texto almacenado
            embedding=vector
        ))
        db.commit()
    except Exception:
        db.rollback()
    
    return vector
