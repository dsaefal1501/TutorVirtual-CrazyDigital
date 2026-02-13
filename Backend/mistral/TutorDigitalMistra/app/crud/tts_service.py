"""
Servicio de Text-to-Speech — edge-tts (Microsoft Neural Voices)
Convierte texto a audio usando las voces neurales gratuitas de Microsoft Edge.
Rápido, consistente y sin coste.
"""
import asyncio
import edge_tts

# ============================================================================
# Configuración de Voces
# ============================================================================

# Voces españolas disponibles en edge-tts
VOCES_DISPONIBLES = {
    "alvaro": "es-ES-AlvaroNeural",       # Masculina España
    "elvira": "es-ES-ElviraNeural",        # Femenina España
    "jorge": "es-MX-JorgeNeural",          # Masculina México
    "dalia": "es-MX-DaliaNeural",          # Femenina México
}

VOZ_DEFAULT = "es-ES-AlvaroNeural"


def _speed_to_rate(speed: float) -> str:
    """
    Convierte un valor numérico de velocidad (ej: 1.35) al formato
    de porcentaje que usa edge-tts (ej: "+35%").
    
    speed=1.0 → "+0%", speed=1.5 → "+50%", speed=0.5 → "-50%"
    """
    # Limitar el rango razonable
    speed = max(0.25, min(3.0, speed))
    percentage = int((speed - 1.0) * 100)
    sign = "+" if percentage >= 0 else ""
    return f"{sign}{percentage}%"


def _resolver_voz(voz: str) -> str:
    """Resuelve el nombre corto de voz a su ID completo de edge-tts."""
    if voz in VOCES_DISPONIBLES:
        return VOCES_DISPONIBLES[voz]
    elif voz.startswith("es-"):
        return voz
    else:
        print(f"[TTS] Voz '{voz}' no reconocida, usando {VOZ_DEFAULT}")
        return VOZ_DEFAULT


async def _generar_audio_async(
    texto: str,
    voz: str = VOZ_DEFAULT,
    speed: float = 1.0,
) -> bytes:
    """
    Genera audio desde texto usando edge-tts (async).
    Retorna bytes del audio MP3.
    """
    rate = _speed_to_rate(speed)
    
    communicate = edge_tts.Communicate(
        text=texto,
        voice=voz,
        rate=rate,
    )
    
    audio_chunks = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
    
    return b"".join(audio_chunks)


async def generar_audio_tts_async(
    texto: str,
    voz: str = "alvaro",
    speed: float = 1.0,
) -> bytes:
    """
    Genera audio desde texto usando edge-tts (versión async directa).
    Ideal para llamar desde endpoints async de FastAPI.
    
    Args:
        texto: El texto a convertir en audio
        voz: Nombre corto de la voz (alvaro, elvira, jorge, dalia) o nombre completo
        speed: Velocidad de reproducción (0.25 a 3.0, donde 1.0 es normal)
    
    Returns:
        bytes del audio generado (formato mp3)
    """
    if not texto or not texto.strip():
        raise ValueError("El texto no puede estar vacío")
    
    voice_id = _resolver_voz(voz)
    print(f"[TTS edge-tts async] texto='{texto[:60]}...', voz={voice_id}, speed={speed}")
    
    return await _generar_audio_async(texto, voice_id, speed)


def generar_audio_tts(
    texto: str,
    voz: str = "alvaro",
    instrucciones: str = None,  # Se mantiene por compatibilidad, pero no se usa
    speed: float = 1.0,
) -> bytes:
    """
    Genera audio desde texto usando edge-tts (Microsoft Neural Voices).
    Versión síncrona — wrapper para compatibilidad.
    
    Args:
        texto: El texto a convertir en audio
        voz: Nombre corto de la voz (alvaro, elvira, jorge, dalia) o nombre completo
        instrucciones: No se usa en edge-tts (se mantiene por compatibilidad)
        speed: Velocidad de reproducción (0.25 a 3.0, donde 1.0 es normal)
    
    Returns:
        bytes del audio generado (formato mp3)
    
    Raises:
        ValueError: Si la voz no es válida o el texto está vacío
        Exception: Si hay error en la generación
    """
    if not texto or not texto.strip():
        raise ValueError("El texto no puede estar vacío")
    
    voice_id = _resolver_voz(voz)
    print(f"[TTS edge-tts] texto='{texto[:60]}...', voz={voice_id}, speed={speed}")
    
    # Ejecutar la coroutine async de forma síncrona
    try:
        # Intentar obtener un event loop existente
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Si ya hay un loop corriendo (ej: dentro de FastAPI con uvicorn),
            # crear un nuevo loop en un thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(
                    asyncio.run,
                    _generar_audio_async(texto, voice_id, speed)
                ).result(timeout=60)
            return result
        else:
            return loop.run_until_complete(
                _generar_audio_async(texto, voice_id, speed)
            )
    except RuntimeError:
        # No hay event loop, crear uno nuevo
        return asyncio.run(
            _generar_audio_async(texto, voice_id, speed)
        )
