"""
Servicio de Text-to-Speech — Azure gpt-4o-mini-tts
Convierte texto a audio usando el deployment de Azure OpenAI.
"""
import os
import httpx
from typing import Optional

# ============================================================================
# Configuración del Cliente TTS
# ============================================================================

AZURE_TTS_ENDPOINT = os.getenv("AZURE_TTS_ENDPOINT", "")
AZURE_TTS_API_KEY = os.getenv("AZURE_TTS_API_KEY", "")
AZURE_TTS_DEPLOYMENT = os.getenv("AZURE_TTS_DEPLOYMENT", "gpt-4o-mini-tts")
TTS_API_VERSION = "2025-03-01-preview"

# Voces disponibles en gpt-4o-mini-tts
VOCES_DISPONIBLES = ["onyx"]


def generar_audio_tts(
    texto: str,
    voz: str = "onyx",
    instrucciones: Optional[str] = None,
) -> bytes:
    """
    Genera audio desde texto usando Azure gpt-4o-mini-tts.
    
    Args:
        texto: El texto a convertir en audio
        voz: La voz a usar (onyx)
        instrucciones: Instrucciones opcionales para controlar el estilo de la voz
    
    Returns:
        bytes del audio generado (formato mp3)
    
    Raises:
        ValueError: Si faltan credenciales o parámetros inválidos
        httpx.HTTPStatusError: Si la API responde con error
    """
    if not AZURE_TTS_ENDPOINT or not AZURE_TTS_API_KEY:
        raise ValueError("Faltan credenciales de Azure TTS. Configura AZURE_TTS_ENDPOINT y AZURE_TTS_API_KEY en .env")
    
    if voz not in VOCES_DISPONIBLES:
        raise ValueError(f"Voz '{voz}' no disponible. Opciones: {', '.join(VOCES_DISPONIBLES)}")
    
    # Construir URL del endpoint
    url = (
        f"{AZURE_TTS_ENDPOINT.rstrip('/')}/openai/deployments/"
        f"{AZURE_TTS_DEPLOYMENT}/audio/speech?api-version={TTS_API_VERSION}"
    )
    
    # Payload
    payload = {
        "model": AZURE_TTS_DEPLOYMENT,
        "input": texto,
        "voice": voz,
    }
    
    # Si hay instrucciones de estilo, agregarlas
    if instrucciones:
        payload["instructions"] = instrucciones
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {AZURE_TTS_API_KEY}",
    }
    
    # Llamada a la API (sincrónica con httpx)
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            print(f"[TTS ERROR] Status: {response.status_code}")
            print(f"[TTS ERROR] Body: {response.text}")
            response.raise_for_status()
        return response.content
