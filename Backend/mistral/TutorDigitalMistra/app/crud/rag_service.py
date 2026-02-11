from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from app.models.modelos import BaseConocimiento, MensajeChat, SesionChat, Usuario, Temario, EmbeddingCache
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
    Mistral = None # Fallback si falla la instalacion

# Configuración del Cliente Mistral
api_key = os.getenv("MISTRAL_API_KEY")
# Configuración del Cliente Mistral
api_key = os.getenv("MISTRAL_API_KEY")
agent_id = "ag_019c417c78a875a6abb18436607fae73" # ID de Nova (Mistral Agent)

# Instanciamos el cliente (Asegúrate de tener: pip install mistralai)
if api_key and Mistral:
    client = Mistral(api_key=api_key)
else:
    client = None # Manejaremos el error si no hay key

# ============================================================================
# RATE LIMITING, CACHING & RETRY LOGIC
# ============================================================================

class RateLimiter:
    """
    Controla la frecuencia de peticiones a la API Mistral.
    Permite máximo 10 requests por minuto para evitar rate limit (429).
    """
    def __init__(self, max_requests: int = 10, time_window: float = 60.0):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)
        self.lock = threading.Lock()
    
    def wait_if_needed(self, key: str = "default"):
        """Espera si es necesario para respetar el rate limit."""
        with self.lock:
            now = time.time()
            # Limpiar requests antiguos
            self.requests[key] = [ts for ts in self.requests[key] 
                                   if now - ts < self.time_window]
            
            if len(self.requests[key]) >= self.max_requests:
                # Calcular espera necesaria
                wait_time = self.time_window - (now - self.requests[key][0])
                if wait_time > 0:
                    time.sleep(wait_time)
                    now = time.time()
                    self.requests[key] = [ts for ts in self.requests[key] 
                                         if now - ts < self.time_window]
            
            self.requests[key].append(now)

rate_limiter = RateLimiter(max_requests=10, time_window=60.0)



def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """
    Decorator para reintentar peticiones fallidas con backoff exponencial.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    # Detectar si es error 429 (rate limit)
                    if "429" in str(e) or "rate_limit" in str(e):
                        wait_time = base_delay * (2 ** attempt)  # Exponential backoff
                        print(f"Rate limit detectado. Reintentando en {wait_time}s (intento {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                    elif attempt < max_retries - 1:
                        wait_time = base_delay * (2 ** attempt)
                        print(f"Error: {str(e)}. Reintentando en {wait_time}s (intento {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
            
            # Si todos los reintentos fallaron
            raise last_exception
        
        return wrapper
    return decorator

@retry_with_backoff(max_retries=3, base_delay=1.0)
def _generate_embedding_internal(texto: str):
    """
    Llama a la API de Mistral para generar embeddings.
    Con reintentos exponenciales y caché.
    """
    if not client:
        return [0.0] * 1024
    
    # Rate limiting
    rate_limiter.wait_if_needed(key="embeddings")
    
    embeddings_batch_response = client.embeddings.create(
        model="mistral-embed",
        inputs=[texto],
    )
    return embeddings_batch_response.data[0].embedding

def generar_embedding(db: Session, texto: str):
    """
    Genera el vector numérico para un texto usando Mistral.
    Consulta primero la base de datos (EmbeddingCache) para evitar costes.
    """
    # 1. Calcular Hash del texto
    text_hash = hashlib.sha256(texto.encode('utf-8')).hexdigest()
    
    # 2. Buscar en Cache DB
    cached = db.query(EmbeddingCache).filter(EmbeddingCache.text_hash == text_hash).first()
    if cached:
        return cached.embedding
        
    # 3. Generar si no existe
    vector = _generate_embedding_internal(texto)
    
    # 4. Guardar en DB
    try:
        nuevo_cache = EmbeddingCache(
            text_hash=text_hash,
            original_text=texto,
            embedding=vector
        )
        db.add(nuevo_cache)
        db.commit()
    except Exception as e:
        print(f"Error guardando cache de embedding: {e}")
        # No fallamos la request principal si falla el cache
    
    return vector

@retry_with_backoff(max_retries=3, base_delay=1.0)
def _call_agent_complete(agent_id: str, messages: list):
    """
    Llama al agente Mistral con reintentos automáticos.
    """
    rate_limiter.wait_if_needed(key="agents_complete")
    return client.agents.complete(agent_id=agent_id, messages=messages)

@retry_with_backoff(max_retries=3, base_delay=1.0)
def _call_agent_stream(agent_id: str, messages: list):
    """
    Llama al agente Mistral en modo streaming con reintentos automáticos.
    """
    rate_limiter.wait_if_needed(key="agents_stream")
    return client.agents.stream(agent_id=agent_id, messages=messages)

def buscar_contexto(db: Session, vector_pregunta: list) -> list[BaseConocimiento]:
    """
    Busca en la base de datos los 3 fragmentos más similares al vector de la pregunta.
    """
    # Usamos el operador de distancia coseno (<=>) de pgvector
    # Nota: Asegúrate de que la columna embedding en modelos.py sea Vector(1536)
    
    # Consulta usando SQLAlchemy 2.0 style
    stmt = select(BaseConocimiento).order_by(
        BaseConocimiento.embedding.cosine_distance(vector_pregunta)
    )
    
    resultados = db.execute(stmt).scalars().all()
    return resultados

def _obtener_o_crear_sesion(db: Session, usuario_id: int, sesion_id_input: int | None = None) -> SesionChat:
    """
    Busca una sesión existente para el usuario o crea una nueva si no existe.
    Garantiza que el usuario tenga un hilo de conversación continuo.
    """
    if sesion_id_input:
        # Intentar recuperar la sesión específica
        sesion = db.query(SesionChat).filter(
            SesionChat.id == sesion_id_input, 
            SesionChat.alumno_id == usuario_id
        ).first()
        if sesion:
            return sesion
    
    # Buscar la última sesión activa del usuario para darle continuidad (Memoria)
    ultima_sesion = db.query(SesionChat).filter(
        SesionChat.alumno_id == usuario_id
    ).order_by(SesionChat.fecha_inicio.desc()).first()

    if ultima_sesion:
        return ultima_sesion

    # Si no hay ninguna sesión previa, crear una nueva
    nueva_sesion = SesionChat(
        alumno_id=usuario_id,
        titulo_resumen=f"Chat del alumno {usuario_id}", # Se puede actualizar luego con LLM
        fecha_inicio=func.now()
    )
    db.add(nueva_sesion)
    db.commit()
    db.refresh(nueva_sesion)
    return nueva_sesion

def _recuperar_historial(db: Session, sesion_id: int, limite: int = 10) -> list[dict]:
    """
    Recupera los últimos mensajes de la sesión para el contexto del LLM.
    """
    # IMPORTANTE: Ordenamos DESC para obtener los RECIENTES, luego invertimos
    historial_msgs = db.query(MensajeChat).filter(
        MensajeChat.sesion_id == sesion_id
    ).order_by(MensajeChat.fecha.desc()).limit(limite).all()
    
    # Reordenar cronológicamente (Antiguo -> Nuevo) para el chat
    historial_msgs.reverse() 
    
    mensajes_formateados = []
    for msg in historial_msgs:
        role = "assistant" if msg.rol == "assistant" else "user"
        mensajes_formateados.append({"role": role, "content": msg.texto})
    
    return mensajes_formateados

def _guardar_mensaje(db: Session, sesion_id: int, rol: str, texto: str, embedding: list = None):
    """
    Guarda un mensaje en el historial, opcionalmente con su embedding.
    """
    nuevo_mensaje = MensajeChat(
        sesion_id=sesion_id,
        rol=rol,
        texto=texto,
        embedding=embedding
    )
    db.add(nuevo_mensaje)
    db.commit()

def preguntar_al_tutor(db: Session, pregunta: PreguntaUsuario) -> RespuestaTutor:
    """
    Orquesta todo el flujo: Sesión -> Pregunta -> RAG -> Historial -> Respuesta (No Streaming)
    """
    # 1. Gestión de Sesión (Memoria continua)
    sesion = _obtener_o_crear_sesion(db, pregunta.usuario_id, pregunta.sesion_id)
    pregunta.sesion_id = sesion.id # Aseguramos que el objeto tenga el ID correcto

    # 2. Generar Embedding y Buscar Contexto
    vector_pregunta = generar_embedding(db, pregunta.texto)
    contexto_docs = buscar_contexto(db, vector_pregunta)
    texto_contexto = "\n\n".join([f"- {doc.contenido}" for doc in contexto_docs])
    
    # 3. Datos del Usuario
    usuario = db.query(Usuario).filter(Usuario.id == pregunta.usuario_id).first()
    nombre_usuario = usuario.nombre if usuario else "Estudiante"
    
    # 4. Construir Prompt con Estructura Correcta (System + History + User)
    
    instrucciones_sistema = (
        "ACTÚA COMO: Un Tutor Virtual experto, amigable y preciso. "
        "OBJETIVO: Ayudar al estudiante basándote en el Contexto RAG proporcionado. "
        "REGLAS DE ESTILO: "
        "1. Inicia TU respuesta SIEMPRE con una etiqueta de emoción: [Happy], [Thinking], [Angry], [Neutral], [Explaining]. "
        "   Ejemplo: '[Happy] ¡Buena pregunta!' o '[Explaining] Mira, funciona así...' "
        "2. IMPORTANTE: NO saludes repetidamente (Hola, Bienvenido, etc.) si ya hay una conversación en curso. Ve directo al grano. "
        "3. Mantén la continuidad de la charla anterior. "
        "4. Si la respuesta no está en el contexto, usa tu conocimiento general pero avisa que es información externa."
    )
    
    # Construir lista de mensajes: [System, ...History, User]
    nuevos_mensajes = [{"role": "system", "content": instrucciones_sistema}]
    
    # Añadir historial recuperado
    nuevos_mensajes.extend(mensajes_llm) 
    
    # Añadir mensaje actual con contexto
    prompt_usuario = f"Contexto RAG recuperado:\n{texto_contexto}\n\nPregunta del usuario ({nombre_usuario}): {pregunta.texto}"
    nuevos_mensajes.append({"role": "user", "content": prompt_usuario})

    # Guardar pregunta del usuario
    _guardar_mensaje(db, sesion.id, "user", pregunta.texto, embedding=vector_pregunta)

    # 5. Llamar al LLM (AGENT) con reintentos
    respuesta_texto = ""
    if client:
        try:
            rate_limiter.wait_if_needed(key="agents_complete")
            chat_response = _call_agent_complete(agent_id, nuevos_mensajes)
            respuesta_texto = chat_response.choices[0].message.content
        except Exception as e:
            respuesta_texto = f"[Neutral] Error al comunicar con Mistral: {str(e)}"
    else:
        respuesta_texto = "[Neutral] Error: No API Key (Modo Simulación)"

    # 6. Guardar Respuesta
    _guardar_mensaje(db, sesion.id, "assistant", respuesta_texto)

    return RespuestaTutor(
        sesion_id=sesion.id,
        respuesta=respuesta_texto,
        fuentes=[f"ID: {doc.id}" for doc in contexto_docs]
    )

def preguntar_al_tutor_stream(db: Session, pregunta: PreguntaUsuario):
    """
    Generador para streaming de respuesta (SSE) con PERSISTENCIA y MEMORIA.
    """
    # 1. Gestión de Sesión
    sesion = _obtener_o_crear_sesion(db, pregunta.usuario_id, pregunta.sesion_id)
    
    # Enviar ID al cliente primero
    if sesion.id != pregunta.sesion_id:
        yield f"__SESION_ID__:{sesion.id}\n"
    pregunta.sesion_id = sesion.id 

    # 2. Contexto y RAG
    vector_pregunta = generar_embedding(db, pregunta.texto)
    contexto_docs = buscar_contexto(db, vector_pregunta)
    texto_contexto = "\n\n".join([f"- {doc.contenido}" for doc in contexto_docs])

    usuario = db.query(Usuario).filter(Usuario.id == pregunta.usuario_id).first()
    nombre_usuario = usuario.nombre if usuario else "Estudiante"

    # 3. Historial y System Prompt
    mensajes_llm = _recuperar_historial(db, sesion.id)

    instrucciones_sistema = (
        "ACTÚA COMO: Un Tutor Virtual experto. "
        "REGLAS: "
        "1. Inicia respuesta con: [Happy], [Thinking], [Angry], [Neutral], [Explaining]. "
        "   Ejemplo: '[Thinking] Analicemos tu duda...' "
        "2. NO saludes si no es necesario. Sé directo y mantén continuidad. "
    )

    nuevos_mensajes = [{"role": "system", "content": instrucciones_sistema}]
    nuevos_mensajes.extend(mensajes_llm)

    prompt_usuario = f"Contexto RAG:\n{texto_contexto}\n\nPregunta ({nombre_usuario}): {pregunta.texto}"
    nuevos_mensajes.append({"role": "user", "content": prompt_usuario})

    # Guardar pregunta
    _guardar_mensaje(db, sesion.id, "user", pregunta.texto, embedding=vector_pregunta)

    # 4. Llamar al Agente en Streaming con reintentos
    texto_completo_respuesta = ""
    
    if client:
        try:
            rate_limiter.wait_if_needed(key="agents_stream")
            stream_response = _call_agent_stream(agent_id, nuevos_mensajes)
            
            for chunk in stream_response:
                content = chunk.data.choices[0].delta.content
                if content:
                    texto_completo_respuesta += content
                    yield content
        except Exception as e:
            yield f"[Neutral] Error stream: {str(e)}"
    else:
        err_msg = "[Neutral] Error: No API Key."
        texto_completo_respuesta = err_msg
        yield err_msg

    # 5. Guardar Respuesta completa
    _guardar_mensaje(db, sesion.id, "assistant", texto_completo_respuesta)

def agregar_conocimiento(db: Session, datos: ConocimientoCreate):
    """
    Agrega un nuevo fragmento de conocimiento a la base de datos vectorial.
    1. Genera el embedding del contenido.
    2. Guarda en la tabla BaseConocimiento.
    """
    # 1. Generar Embedding
    vector_contenido = generar_embedding(db, datos.contenido)
    
    # 2. Crear registro
    nuevo_conocimiento = BaseConocimiento(
        temario_id=datos.temario_id,
        contenido=datos.contenido,
        embedding=vector_contenido,
        metadata_info=datos.metadatos # Mapea al campo 'metadatos' JSON
    )
    
    db.add(nuevo_conocimiento)
    db.commit()
    db.refresh(nuevo_conocimiento)
    return nuevo_conocimiento

def sincronizar_temario_a_conocimiento(db: Session) -> int:
    """
    Recorre la tabla Temario y convierte las descripciones en vectores
    guardándolas en BaseConocimiento si no existen previamente.
    Retorna la cantidad de nuevos registros creados.
    """
    # 1. Obtener todos los temas con descripción
    temas = db.query(Temario).filter(Temario.descripcion != None).all()
    count = 0

    for tema in temas:
        # 2. Verificar si ya existe conocimiento asociado a este tema
        # (Para evitar duplicados en ejecuciones sucesivas)
        existe = db.query(BaseConocimiento).filter(BaseConocimiento.temario_id == tema.id).first()
        if existe:
            continue
            
        # Inyectamos el Nivel y el Orden directamente en el texto que lee la IA
        contenido_texto = f"[Jerarquía: Nivel {tema.nivel} - Orden {tema.orden} - PadreID {tema.parent_id}] Tema: {tema.nombre}. Contenido: {tema.descripcion}"
        
        # 3. Generar Embedding (con rate limiting automático)
        vector = generar_embedding(db, contenido_texto)
        
        # 4. Guardar
        nuevo = BaseConocimiento(
            temario_id=tema.id,
            contenido=contenido_texto,
            embedding=vector,
            metadata_info={"origen": "migracion_automatica", "nivel": tema.nivel, "orden": tema.orden, "parent_id": tema.parent_id}
        )
        db.add(nuevo)
        count += 1
        
        print(f"Procesado tema {tema.id} ({tema.nombre}). Rate limiter gestiona automáticamente la frecuencia.")
    
    db.commit()
    return count


         

      



