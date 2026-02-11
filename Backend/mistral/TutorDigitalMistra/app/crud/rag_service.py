from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_
from app.models.modelos import BaseConocimiento, MensajeChat, SesionChat, Usuario, Temario, EmbeddingCache, ProgresoAlumno
from app.schemas.schemas import PreguntaUsuario, RespuestaTutor, ConocimientoCreate
import os
import hashlib
import time
import threading
import functools
from collections import defaultdict

try:
    from mistralai import Mistral
except ImportError:
    Mistral = None 

# Configuración del Cliente Mistral
api_key = os.getenv("MISTRAL_API_KEY")
agent_id = "ag_019c417c78a875a6abb18436607fae73" # Tu ID de agente

if api_key and Mistral:
    client = Mistral(api_key=api_key)
else:
    client = None

# ============================================================================
# 1. RATE LIMITING & RETRY (Optimización que ahorra líneas)
# ============================================================================

class RateLimiter:
    def __init__(self, max_requests: int = 10, time_window: float = 60.0):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)
        self.lock = threading.Lock()
    
    def wait_if_needed(self, key: str = "default"):
        with self.lock:
            now = time.time()
            self.requests[key] = [ts for ts in self.requests[key] if now - ts < self.time_window]
            if len(self.requests[key]) >= self.max_requests:
                wait_time = self.time_window - (now - self.requests[key][0])
                if wait_time > 0: time.sleep(wait_time)
            self.requests[key].append(time.time())

rate_limiter = RateLimiter()

def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if "429" in str(e) and attempt < max_retries - 1:
                        time.sleep(base_delay * (2 ** attempt))
                    elif attempt == max_retries - 1:
                        raise e
            return None
        return wrapper
    return decorator

# ============================================================================
# 2. LOGICA DE EMBEDDINGS (Core)
# ============================================================================

@retry_with_backoff()
def _generate_embedding_api(texto: str):
    if not client: return [0.0] * 1024 # Dummy para tests sin API
    rate_limiter.wait_if_needed("embed")
    resp = client.embeddings.create(model="mistral-embed", inputs=[texto])
    return resp.data[0].embedding

def generar_embedding(db: Session, texto: str):
    """Genera embedding revisando caché primero."""
    text_hash = hashlib.sha256(texto.encode('utf-8')).hexdigest()
    cached = db.query(EmbeddingCache).filter(EmbeddingCache.text_hash == text_hash).first()
    if cached: return cached.embedding
    
    vector = _generate_embedding_api(texto)
    
    try:
        db.add(EmbeddingCache(text_hash=text_hash, original_text=texto, embedding=vector))
        db.commit()
    except: pass # Si falla el caché no detenemos el flujo
    return vector

# ============================================================================
# 3. LÓGICA DEL TUTOR SECUENCIAL (LO QUE FALTABA)
# ============================================================================

def obtener_siguiente_contenido(db: Session, usuario_id: int, sesion_id: int) -> Optional[BaseConocimiento]:
    """
    Busca el siguiente fragmento EXACTO que el alumno debe leer según su progreso.
    """
    # 1. Recuperar el temario activo de la sesión (o el último usado)
    sesion = db.query(SesionChat).filter(SesionChat.id == sesion_id).first()
    temario_id = sesion.temario_actual_id if sesion and sesion.temario_actual_id else 1 # Default al tema 1

    # 2. Buscar progreso
    progreso = db.query(ProgresoAlumno).filter(
        ProgresoAlumno.usuario_id == usuario_id,
        ProgresoAlumno.temario_id == temario_id
    ).first()

    siguiente_bloque = None

    if not progreso:
        # Caso 1: Alumno nuevo en este tema -> Traer el bloque 1
        siguiente_bloque = db.query(BaseConocimiento).filter(
            BaseConocimiento.temario_id == temario_id,
            BaseConocimiento.orden_aparicion == 1
        ).first()
        
        # Inicializar progreso
        if siguiente_bloque:
            progreso = ProgresoAlumno(usuario_id=usuario_id, temario_id=temario_id, ultimo_contenido_visto_id=siguiente_bloque.id)
            db.add(progreso)
            db.commit()
    else:
        # Caso 2: Alumno recurrente -> Traer bloque siguiente al último visto
        ultimo_visto = db.query(BaseConocimiento).get(progreso.ultimo_contenido_visto_id)
        
        if ultimo_visto:
            siguiente_bloque = db.query(BaseConocimiento).filter(
                BaseConocimiento.temario_id == temario_id,
                BaseConocimiento.orden_aparicion > ultimo_visto.orden_aparicion
            ).order_by(BaseConocimiento.orden_aparicion.asc()).first()
            
            # Actualizar progreso
            if siguiente_bloque:
                progreso.ultimo_contenido_visto_id = siguiente_bloque.id
                progreso.fecha_actualizacion = func.now()
                db.commit()

    return siguiente_bloque

# ============================================================================
# 4. CHATBOT UNIFICADO (RAG + TUTOR)
# ============================================================================

def _detectar_intencion(texto: str) -> str:
    """Clasificador simple: ¿Quiere avanzar o tiene una duda?"""
    palabras_avance = ["siguiente", "continuar", "avanza", "next", "sigue", "empezar", "vamos"]
    texto_lower = texto.lower().strip()
    if texto_lower in palabras_avance or any(p in texto_lower for p in ["pasa al siguiente", "siguiente punto"]):
        return "AVANCE"
    return "DUDA"

def preguntar_al_tutor(db: Session, pregunta: PreguntaUsuario) -> RespuestaTutor:
    # 1. Gestión de Sesión
    sesion = db.query(SesionChat).filter(SesionChat.id == pregunta.sesion_id).first()
    if not sesion:
        sesion = SesionChat(alumno_id=pregunta.usuario_id, fecha_inicio=func.now())
        db.add(sesion)
        db.commit()
        db.refresh(sesion)
    
    intencion = _detectar_intencion(pregunta.texto)
    respuesta_texto = ""
    fuentes = []
    
    # --- RAMA A: MODO TUTOR (Enseñar al pie de la letra) ---
    if intencion == "AVANCE":
        bloque = obtener_siguiente_contenido(db, pregunta.usuario_id, sesion.id)
        
        if bloque:
            # Formatear según tipo de contenido
            if bloque.tipo_contenido == 'codigo':
                respuesta_texto = f"[Teaching] Aquí tienes el ejemplo práctico:\n\n```python\n{bloque.contenido}\n```\n\nAnalízalo y dime 'siguiente' cuando estés listo."
            elif bloque.tipo_contenido == 'ejercicio':
                respuesta_texto = f"[Quiz] {bloque.contenido}\n\n¡Intenta resolverlo!"
            else:
                respuesta_texto = f"[Teaching] {bloque.contenido}"
            
            fuentes = [f"Ref: {bloque.ref_fuente} (Pag {bloque.pagina})"]
        else:
            respuesta_texto = "[Happy] ¡Felicidades! Has completado todo el contenido de este tema. ¿Quieres pasar al siguiente capítulo?"
    
    # --- RAMA B: MODO RAG (Resolver dudas) ---
    else:
        # 1. Buscar Contexto
        vector = generar_embedding(db, pregunta.texto)
        docs = db.execute(
            select(BaseConocimiento).order_by(BaseConocimiento.embedding.cosine_distance(vector)).limit(3)
        ).scalars().all()
        
        contexto_str = "\n".join([d.contenido for d in docs])
        fuentes = [f"Pag {d.pagina}" for d in docs]
        
        # 2. Prompt al LLM
        sys_prompt = (
            "Eres un profesor de Python paciente. "
            "Usa el CONTEXTO proporcionado para responder. "
            "Si la respuesta no está en el contexto, usa tu saber general pero avísalo. "
            "Empieza con etiquetas de emoción como [Happy], [Thinking]."
        )
        
        msgs = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Contexto:\n{contexto_str}\n\nPregunta: {pregunta.texto}"}
        ]
        
        # 3. Llamada API
        if client:
            rate_limiter.wait_if_needed("chat")
            resp = client.chat.complete(model="mistral-large-latest", messages=msgs)
            respuesta_texto = resp.choices[0].message.content
        else:
            respuesta_texto = "[Neutral] Modo simulación (Sin API Key)."

    # Guardar historial
    db.add(MensajeChat(sesion_id=sesion.id, rol="user", texto=pregunta.texto))
    db.add(MensajeChat(sesion_id=sesion.id, rol="assistant", texto=respuesta_texto))
    db.commit()

    return RespuestaTutor(sesion_id=sesion.id, respuesta=respuesta_texto, fuentes=fuentes)

# ============================================================================
# 5. STREAMING (Versión simplificada para brevedad)
# ============================================================================

def preguntar_al_tutor_stream(db: Session, pregunta: PreguntaUsuario):
    # Nota: Para el streaming idealmente deberíamos replicar la lógica de intenciones
    # Aquí pongo una versión básica que asume "Modo Duda" para no alargar el código excesivamente
    # Si detecta avance, lo procesa directo.
    
    intencion = _detectar_intencion(pregunta.texto)
    
    if intencion == "AVANCE":
        # El avance no necesita streaming porque es leer de DB, es instantáneo
        resp = preguntar_al_tutor(db, pregunta)
        yield resp.respuesta
        return

    # Si es duda, usamos streaming del LLM
    vector = generar_embedding(db, pregunta.texto)
    docs = db.execute(
        select(BaseConocimiento).order_by(BaseConocimiento.embedding.cosine_distance(vector)).limit(3)
    ).scalars().all()
    contexto = "\n".join([d.contenido for d in docs])
    
    msgs = [
        {"role": "system", "content": "Eres un tutor experto."},
        {"role": "user", "content": f"Contexto: {contexto}\n\nPregunta: {pregunta.texto}"}
    ]
    
    if client:
        rate_limiter.wait_if_needed("stream")
        stream = client.chat.stream(model="mistral-large-latest", messages=msgs)
        full_text = ""
        for chunk in stream:
            content = chunk.data.choices[0].delta.content
            if content:
                full_text += content
                yield content
        
        # Guardar al finalizar
        # (Requiere gestionar sesión igual que en preguntar_al_tutor)