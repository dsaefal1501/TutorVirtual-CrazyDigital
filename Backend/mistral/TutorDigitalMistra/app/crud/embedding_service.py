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

BATCH_SIZE = 20  # Cuántos textos enviar por llamada API (máx recomendado ~20)

@retry_with_backoff()
def _generate_embedding_api(texto: str) -> List[float]:
    """Llama a la API de OpenAI para generar un embedding (1 texto)."""
    if not openai_client:
        return [0.0] * EMBEDDING_DIM
    
    rate_limiter.wait_if_needed("embed")
    
    texto_limpio = texto.replace("\n", " ").strip()
    if not texto_limpio:
        return [0.0] * EMBEDDING_DIM
    
    response = openai_client.embeddings.create(
        model=EMBEDDING_DEPLOYMENT,
        input=[texto_limpio]
    )
    return response.data[0].embedding


@retry_with_backoff()
def _generate_embeddings_batch_api(textos: List[str]) -> List[List[float]]:
    """Llama a la API de OpenAI para generar embeddings en BATCH (múltiples textos)."""
    if not openai_client:
        return [[0.0] * EMBEDDING_DIM for _ in textos]
    
    rate_limiter.wait_if_needed("embed")
    
    textos_limpios = [t.replace("\n", " ").strip() for t in textos]
    # Reemplazar vacíos por un espacio para evitar errores
    textos_limpios = [t if t else " " for t in textos_limpios]
    
    response = openai_client.embeddings.create(
        model=EMBEDDING_DEPLOYMENT,
        input=textos_limpios
    )
    
    # Ordenar por índice (la API puede devolver desordenado)
    results = sorted(response.data, key=lambda x: x.index)
    return [r.embedding for r in results]


def generar_embedding(db: Session, texto: str) -> List[float]:
    """
    Genera un embedding revisando caché primero.
    Si no existe en caché, llama a OpenAI text-embedding-3-small.
    """
    text_hash = hashlib.sha256(texto.encode('utf-8')).hexdigest()
    
    cached = db.query(EmbeddingCache).filter(
        EmbeddingCache.text_hash == text_hash
    ).first()
    
    if cached:
        return cached.embedding
    
    vector = _generate_embedding_api(texto)
    
    try:
        db.add(EmbeddingCache(
            text_hash=text_hash,
            original_text=texto[:2000],
            embedding=vector
        ))
        db.commit()
    except Exception:
        db.rollback()
    
    return vector


def generar_embeddings_batch(db: Session, textos: List[str]) -> List[List[float]]:
    """
    Genera embeddings en BATCH — mucho más rápido que uno por uno.
    Revisa caché primero, solo envía a la API los que faltan.
    Retorna una lista de vectores en el mismo orden que los textos de entrada.
    """
    resultados = [None] * len(textos)
    indices_sin_cache = []
    textos_sin_cache = []
    
    # 1. Buscar en caché
    for i, texto in enumerate(textos):
        text_hash = hashlib.sha256(texto.encode('utf-8')).hexdigest()
        cached = db.query(EmbeddingCache).filter(
            EmbeddingCache.text_hash == text_hash
        ).first()
        if cached:
            resultados[i] = cached.embedding
        else:
            indices_sin_cache.append(i)
            textos_sin_cache.append(texto)
    
    if not textos_sin_cache:
        print(f"   [Cache] Todos los {len(textos)} embeddings estaban en caché ✓")
        return resultados
    
    print(f"   [Embedding] {len(textos) - len(textos_sin_cache)} en caché, {len(textos_sin_cache)} por generar...")
    
    # 2. Generar en batches
    todos_vectores = []
    for batch_start in range(0, len(textos_sin_cache), BATCH_SIZE):
        batch_textos = textos_sin_cache[batch_start:batch_start + BATCH_SIZE]
        batch_num = (batch_start // BATCH_SIZE) + 1
        total_batches = (len(textos_sin_cache) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"   [Embedding] Batch {batch_num}/{total_batches} ({len(batch_textos)} textos)...")
        
        vectores = _generate_embeddings_batch_api(batch_textos)
        todos_vectores.extend(vectores)
    
    # 3. Asignar resultados y cachear
    for j, idx_original in enumerate(indices_sin_cache):
        vector = todos_vectores[j]
        resultados[idx_original] = vector
        
        texto = textos[idx_original]
        text_hash = hashlib.sha256(texto.encode('utf-8')).hexdigest()
        try:
            db.add(EmbeddingCache(
                text_hash=text_hash,
                original_text=texto[:2000],
                embedding=vector
            ))
        except Exception:
            pass
    
    try:
        db.commit()
    except Exception:
        db.rollback()
    
    print(f"   [Embedding] ✓ {len(textos_sin_cache)} embeddings generados y cacheados")
    return resultados
