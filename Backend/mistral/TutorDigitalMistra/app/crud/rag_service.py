from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session, joinedload
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
# SYSTEM PROMPT COMPLETO DE PABLO
# ============================================================================

PABLO_SYSTEM_PROMPT = """
ROL Y PERSONALIDAD
Eres "Pablo", un tutor virtual experto, paciente y entusiasta. Tu objetivo es guiar al estudiante en su proceso de aprendizaje.

Tono: Amigable, profesional, motivador y adaptativo.
Formato: Conversacional, fluido y natural (como hablar cara a cara).
Identidad: Eres un avatar 3D en un entorno educativo. Nunca menciones que eres una IA, un modelo de lenguaje o un script.

METODOLOGÍA PEDAGÓGICA (Socrática)
- No des la respuesta directa inmediatamente. Haz preguntas guía para que el alumno llegue a la conclusión por sí mismo, a no ser que el alumno te lo pida.
- Corrección positiva: Si el alumno se equivoca, corrige con delicadeza, explica el porqué del error y propón un nuevo intento.
- Adaptabilidad: Ajusta tu vocabulario al nivel del usuario. Si es principiante, usa analogías simples.
- Refuerzo: Felicita los aciertos explícitamente para mantener la motivación alta.
- Verificación: Al terminar una explicación, verifica la comprensión: "¿Te hace sentido?", "¿Seguimos?", o "¿Probamos un ejemplo?".

MEMORIA Y CONTINUIDAD (CRÍTICO)
- No eres una entidad aislada; tienes acceso al historial de la conversación actual.
- Hilo Conversacional: Antes de responder, analiza los mensajes anteriores. Si el usuario dice "Continúa" o "Dame un ejemplo", debes saber exactamente de qué tema estabais hablando.
- Referencias al Pasado: Conecta los puntos. Usa frases como: "Como mencionamos hace un momento...", "Retomando tu duda sobre [Tema Anterior]...".
- Evita Repeticiones: Si el usuario ya se presentó o ya confirmó que entendió un concepto, no se lo vuelvas a preguntar.
- Persistencia: Si la conversación se interrumpió y el usuario regresa, saluda con un "¡Hola de nuevo! Nos quedamos viendo [Último Tema]. ¿Listo para seguir?".

LÓGICA DE NAVEGACIÓN Y JERARQUÍA (METADATOS)
Tu conocimiento no es una lista plana. Usarás los metadatos parent_id y orden inyectados en el contexto para saber dónde estás y qué sigue.

Interpretación de Metadatos:
- Cada fragmento de información tiene un parent_id (el tema contenedor) y un orden (su posición relativa).
- Regla de Oro: Si estás explicando un contenido con parent_id: X y orden: 1, el siguiente paso lógico es buscar en tu conocimiento el parent_id: X con orden: 2.
- En la jerarquía cada nivel se asigna a un tipo de información:
  - nivel 1 es el tema 1
  - nivel 2 es un punto 1.1
  - nivel 3 es un subpunto 1.1.1

Continuidad Secuencial:
- No saltes a otro tema (parent_id) hasta no haber cubierto los puntos de orden superior del tema actual, a menos que el usuario lo pida.
- Si el alumno está en el punto 1.1, no pases al Tema 2 hasta validar si existe un punto 1.2.

Ubicación al Usuario:
- Si el alumno pregunta "¿Dónde estamos?", usa el nombre del tema asociado al parent_id para darle contexto.
- Si el alumno se pierde, recuérdale dónde está: "Estamos en el subtema [Nombre] del capítulo [Padre]".

REGLA CRÍTICA SOBRE EL CONTENIDO DEL LIBRO:
- Cuando el alumno pide que le enseñes o expliques un tema, DEBES usar el contenido LITERAL del libro que se te proporciona en el CONTEXTO.
- NO inventes ni parafrasees el contenido del libro. Usa las palabras exactas que aparecen en el CONTEXTO.
- Si el contenido tiene código, muéstralo TAL CUAL aparece en el libro.
- Puedes añadir tus propias explicaciones DESPUÉS de presentar el contenido del libro, pero siempre deja claro qué es del libro y qué es tu aporte.

PROTOCOLO DE RESPUESTA (EMOCIONES Y FORMATO)
Etiqueta de Emoción (OBLIGATORIA al inicio):
- [Happy]: Saludos, éxitos, refuerzo positivo.
- [Thinking]: Analizando dudas, buscando en el temario, reflexionando.
- [Explaining]: Explicando conceptos, dando lecciones.
- [Neutral]: Confirmaciones, transiciones, escucha activa.
- [Angry]: (Casi nunca) Solo ante ofensas graves.

Estilo de Voz: Usa frases de longitud moderada. Evita listas interminables o tablas complejas.

SEGURIDAD
- Si el tema es ofensivo, ilegal o fuera del ámbito educativo, redirige amablemente al estudio.
- Protege la privacidad de datos de terceros.
""".strip()

# ============================================================================
# 1. RATE LIMITING & RETRY
# ============================================================================

class RateLimiter:
    def __init__(self, max_requests: int = 20, time_window: float = 60.0):
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
    if not client: return [0.0] * 1024
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
    except: pass
    return vector

# ============================================================================
# 3. UTILIDADES DE CONTEXTO JERÁRQUICO
# ============================================================================

def _construir_contexto_enriquecido(db: Session, docs: list) -> str:
    """
    Para cada fragmento recuperado por RAG, construye un contexto que incluye:
    - Nombre del tema y del tema padre
    - Nivel y orden jerárquico
    - Página de referencia
    - El contenido LITERAL del libro
    """
    fragmentos = []
    
    for d in docs:
        # Cargar el tema asociado (y su padre si existe)
        tema = db.query(Temario).filter(Temario.id == d.temario_id).first()
        
        if tema:
            padre_nombre = "Raíz (Libro)"
            if tema.parent_id:
                padre = db.query(Temario).filter(Temario.id == tema.parent_id).first()
                if padre:
                    padre_nombre = padre.nombre
            
            encabezado = (
                f"📖 Tema: {tema.nombre} | Nivel: {tema.nivel} | Orden: {tema.orden} | "
                f"Capítulo Padre: {padre_nombre} | Página: {d.pagina}"
            )
        else:
            encabezado = f"📖 Página: {d.pagina}"
        
        tipo_label = "📝 TEORÍA" if d.tipo_contenido == "texto" else "💻 CÓDIGO"
        
        fragmentos.append(f"{encabezado}\n[{tipo_label}]\n{d.contenido}")
    
    return "\n\n---\n\n".join(fragmentos)


def _cargar_historial(db: Session, sesion_id: int, limite: int = 10) -> list:
    """Carga los últimos N mensajes de la sesión para memoria conversacional."""
    mensajes = db.query(MensajeChat).filter(
        MensajeChat.sesion_id == sesion_id
    ).order_by(MensajeChat.fecha.asc()).all()
    
    # Tomar solo los últimos N mensajes para no sobrecargar el contexto
    ultimos = mensajes[-limite:] if len(mensajes) > limite else mensajes
    
    historial = []
    for m in ultimos:
        historial.append({"role": m.rol, "content": m.texto})
    
    return historial


def _obtener_bloques_tema_completo(db: Session, temario_id: int) -> list:
    """
    Recupera TODOS los bloques de BaseConocimiento de un tema, en orden.
    Esto permite a Pablo enseñar el contenido completo, palabra a palabra.
    """
    bloques = db.query(BaseConocimiento).filter(
        BaseConocimiento.temario_id == temario_id
    ).order_by(BaseConocimiento.orden_aparicion.asc()).all()
    
    return bloques


def _obtener_info_ubicacion(db: Session, temario_id: int) -> str:
    """Construye un string descriptivo de dónde está el alumno en la jerarquía."""
    tema = db.query(Temario).filter(Temario.id == temario_id).first()
    if not tema:
        return "Ubicación desconocida"
    
    padre_nombre = ""
    if tema.parent_id:
        padre = db.query(Temario).filter(Temario.id == tema.parent_id).first()
        if padre:
            padre_nombre = padre.nombre
    
    if padre_nombre:
        return f"Capítulo: {padre_nombre} → Sección: {tema.nombre} (Nivel {tema.nivel}, Orden {tema.orden})"
    else:
        return f"Capítulo: {tema.nombre} (Nivel {tema.nivel}, Orden {tema.orden})"


# ============================================================================
# 4. LÓGICA DEL TUTOR SECUENCIAL
# ============================================================================

def obtener_siguiente_contenido(db: Session, usuario_id: int, sesion_id: int) -> Optional[BaseConocimiento]:
    """
    Busca el siguiente fragmento EXACTO que el alumno debe leer según su progreso.
    """
    sesion = db.query(SesionChat).filter(SesionChat.id == sesion_id).first()
    temario_id = sesion.temario_id if sesion and sesion.temario_id else None

    # Si no hay temario asignado, buscar el primero disponible
    if not temario_id:
        primer_tema = db.query(Temario).filter(Temario.activo == True).order_by(Temario.orden.asc()).first()
        if primer_tema:
            temario_id = primer_tema.id
            if sesion:
                sesion.temario_id = temario_id
                db.commit()
        else:
            return None

    # Buscar progreso del alumno
    progreso = db.query(ProgresoAlumno).filter(
        ProgresoAlumno.usuario_id == usuario_id,
        ProgresoAlumno.temario_id == temario_id
    ).first()

    siguiente_bloque = None

    if not progreso:
        # Alumno nuevo → primer bloque
        siguiente_bloque = db.query(BaseConocimiento).filter(
            BaseConocimiento.temario_id == temario_id,
            BaseConocimiento.orden_aparicion == 1
        ).first()
        
        if siguiente_bloque:
            progreso = ProgresoAlumno(
                usuario_id=usuario_id, 
                temario_id=temario_id, 
                ultimo_contenido_visto_id=siguiente_bloque.id
            )
            db.add(progreso)
            db.commit()
    else:
        # Alumno existente → bloque siguiente al último visto
        ultimo_visto = db.query(BaseConocimiento).get(progreso.ultimo_contenido_visto_id)
        
        if ultimo_visto:
            # Primero buscar más bloques en el MISMO tema
            siguiente_bloque = db.query(BaseConocimiento).filter(
                BaseConocimiento.temario_id == temario_id,
                BaseConocimiento.orden_aparicion > ultimo_visto.orden_aparicion
            ).order_by(BaseConocimiento.orden_aparicion.asc()).first()
            
            if not siguiente_bloque:
                # No hay más bloques en este tema → pasar al siguiente tema
                tema_actual = db.query(Temario).filter(Temario.id == temario_id).first()
                if tema_actual:
                    siguiente_tema = db.query(Temario).filter(
                        Temario.orden > tema_actual.orden,
                        Temario.activo == True
                    ).order_by(Temario.orden.asc()).first()
                    
                    if siguiente_tema:
                        # Actualizar sesión al nuevo tema
                        if sesion:
                            sesion.temario_id = siguiente_tema.id
                            db.commit()
                        
                        siguiente_bloque = db.query(BaseConocimiento).filter(
                            BaseConocimiento.temario_id == siguiente_tema.id,
                            BaseConocimiento.orden_aparicion == 1
                        ).first()
                        
                        # Crear/actualizar progreso para el nuevo tema
                        if siguiente_bloque:
                            nuevo_progreso = ProgresoAlumno(
                                usuario_id=usuario_id,
                                temario_id=siguiente_tema.id,
                                ultimo_contenido_visto_id=siguiente_bloque.id
                            )
                            db.add(nuevo_progreso)
                            db.commit()
                            return siguiente_bloque
            
            # Actualizar progreso
            if siguiente_bloque:
                progreso.ultimo_contenido_visto_id = siguiente_bloque.id
                progreso.fecha_actualizacion = func.now()
                db.commit()

    return siguiente_bloque

# ============================================================================
# 5. CHATBOT UNIFICADO (RAG + TUTOR PABLO)
# ============================================================================

def _detectar_intencion(texto: str) -> str:
    """Clasificador: ¿Quiere avanzar, saber ubicación, o tiene una duda?"""
    texto_lower = texto.lower().strip()
    
    palabras_avance = ["siguiente", "continuar", "avanza", "next", "sigue", "empezar", 
                       "vamos", "continúa", "pasa al siguiente", "siguiente punto",
                       "siguiente tema", "next topic"]
    
    palabras_ubicacion = ["dónde estamos", "donde estamos", "en qué tema", 
                          "en que tema", "qué estamos viendo", "que estamos viendo"]
    
    if any(p in texto_lower for p in palabras_ubicacion):
        return "UBICACION"
    if texto_lower in palabras_avance or any(p in texto_lower for p in palabras_avance):
        return "AVANCE"
    return "DUDA"


def preguntar_al_tutor(db: Session, pregunta: PreguntaUsuario) -> RespuestaTutor:
    # 1. Gestión de Sesión
    sesion = db.query(SesionChat).filter(SesionChat.id == pregunta.sesion_id).first()
    if not sesion:
        sesion = SesionChat(
            alumno_id=pregunta.usuario_id, 
            titulo_resumen="Sesión de estudio",
            fecha_inicio=func.now()
        )
        db.add(sesion)
        db.commit()
        db.refresh(sesion)
    
    intencion = _detectar_intencion(pregunta.texto)
    respuesta_texto = ""
    fuentes = []
    
    # --- RAMA A: MODO UBICACIÓN ---
    if intencion == "UBICACION":
        temario_id = sesion.temario_id if sesion.temario_id else 1
        ubicacion = _obtener_info_ubicacion(db, temario_id)
        respuesta_texto = f"[Neutral] {ubicacion}"
        fuentes = ["Navegación jerárquica"]
    
    # --- RAMA B: MODO TUTOR SECUENCIAL (Enseñar palabra a palabra) ---
    elif intencion == "AVANCE":
        bloque = obtener_siguiente_contenido(db, pregunta.usuario_id, sesion.id)
        
        if bloque:
            # Obtener info jerárquica para dar contexto a Pablo
            tema = db.query(Temario).filter(Temario.id == bloque.temario_id).first()
            ubicacion = _obtener_info_ubicacion(db, bloque.temario_id) if tema else ""
            
            # Construir el contenido completo del bloque con metadatos
            contenido_libro = bloque.contenido
            tipo = bloque.tipo_contenido
            
            # Cargar historial para continuidad
            historial = _cargar_historial(db, sesion.id, limite=6)
            
            # Pedir a Pablo que presente el contenido del libro como tutor
            prompt_contenido = (
                f"UBICACIÓN ACTUAL: {ubicacion}\n\n"
                f"CONTENIDO DEL LIBRO A ENSEÑAR (tipo: {tipo}):\n"
                f"---\n{contenido_libro}\n---\n\n"
                f"INSTRUCCIÓN: Presenta este contenido del libro al alumno de forma natural y pedagógica. "
                f"Usa el texto LITERAL del libro, puedes añadir explicaciones tuyas DESPUÉS. "
                f"Si es código, muéstralo completo. Al final, pregunta si el alumno entendió o quiere un ejemplo."
            )
            
            msgs = [{"role": "system", "content": PABLO_SYSTEM_PROMPT}]
            msgs.extend(historial)
            msgs.append({"role": "user", "content": prompt_contenido})
            
            if client:
                rate_limiter.wait_if_needed("chat")
                resp = client.chat.complete(model="mistral-large-latest", messages=msgs)
                respuesta_texto = resp.choices[0].message.content
            else:
                # Fallback sin API: mostrar contenido directo
                if tipo == 'codigo':
                    respuesta_texto = f"[Explaining] Aquí tienes el ejemplo práctico:\n\n```python\n{contenido_libro}\n```\n\n¿Lo analizamos juntos?"
                else:
                    respuesta_texto = f"[Explaining] {contenido_libro}\n\n¿Te hace sentido? ¿Seguimos?"
            
            fuentes = [f"Ref: {bloque.ref_fuente} (Pag {bloque.pagina})"]
        else:
            respuesta_texto = "[Happy] ¡Felicidades! Has completado todo el contenido disponible. ¿Quieres repasar algún tema en particular?"
    
    # --- RAMA C: MODO RAG (Resolver dudas con contenido del libro) ---
    else:
        # 1. Buscar los fragmentos más relevantes del libro
        vector = generar_embedding(db, pregunta.texto)
        docs = db.execute(
            select(BaseConocimiento).order_by(
                BaseConocimiento.embedding.cosine_distance(vector)
            ).limit(5)  # 5 fragmentos para más contexto
        ).scalars().all()
        
        # 2. Construir contexto enriquecido con jerarquía
        contexto_str = _construir_contexto_enriquecido(db, docs)
        fuentes = [f"Pag {d.pagina}" for d in docs]
        
        # 3. Cargar historial de la sesión
        historial = _cargar_historial(db, sesion.id, limite=10)
        
        # 4. Construir mensajes con el prompt completo de Pablo
        msgs = [{"role": "system", "content": PABLO_SYSTEM_PROMPT}]
        
        # Inyectar historial
        msgs.extend(historial)
        
        # Mensaje del usuario con contexto del libro
        user_msg = (
            f"CONTEXTO DEL LIBRO (usa este contenido LITERAL para responder):\n"
            f"{contexto_str}\n\n"
            f"PREGUNTA DEL ALUMNO: {pregunta.texto}"
        )
        msgs.append({"role": "user", "content": user_msg})
        
        # 5. Llamada a Mistral
        if client:
            rate_limiter.wait_if_needed("chat")
            resp = client.chat.complete(model="mistral-large-latest", messages=msgs)
            respuesta_texto = resp.choices[0].message.content
        else:
            respuesta_texto = "[Neutral] Modo simulación (Sin API Key configurada)."

    # Guardar historial de esta interacción
    db.add(MensajeChat(sesion_id=sesion.id, rol="user", texto=pregunta.texto))
    db.add(MensajeChat(sesion_id=sesion.id, rol="assistant", texto=respuesta_texto))
    db.commit()

    return RespuestaTutor(sesion_id=sesion.id, respuesta=respuesta_texto, fuentes=fuentes)

# ============================================================================
# 6. STREAMING (Con personalidad Pablo completa)
# ============================================================================

def preguntar_al_tutor_stream(db: Session, pregunta: PreguntaUsuario):
    intencion = _detectar_intencion(pregunta.texto)
    
    # Si es AVANCE o UBICACIÓN, no necesita streaming (es lectura de DB)
    if intencion in ("AVANCE", "UBICACION"):
        resp = preguntar_al_tutor(db, pregunta)
        yield resp.respuesta
        return

    # --- Modo DUDA con Streaming ---
    
    # Gestión de sesión
    sesion = db.query(SesionChat).filter(SesionChat.id == pregunta.sesion_id).first()
    if not sesion:
        sesion = SesionChat(
            alumno_id=pregunta.usuario_id, 
            titulo_resumen="Sesión de estudio",
            fecha_inicio=func.now()
        )
        db.add(sesion)
        db.commit()
        db.refresh(sesion)
    
    # Buscar contexto RAG
    vector = generar_embedding(db, pregunta.texto)
    docs = db.execute(
        select(BaseConocimiento).order_by(
            BaseConocimiento.embedding.cosine_distance(vector)
        ).limit(5)
    ).scalars().all()
    
    contexto_str = _construir_contexto_enriquecido(db, docs)
    
    # Cargar historial
    historial = _cargar_historial(db, sesion.id, limite=10)
    
    # Construir mensajes con Pablo completo
    msgs = [{"role": "system", "content": PABLO_SYSTEM_PROMPT}]
    msgs.extend(historial)
    msgs.append({
        "role": "user", 
        "content": f"CONTEXTO DEL LIBRO (usa este contenido LITERAL para responder):\n{contexto_str}\n\nPREGUNTA DEL ALUMNO: {pregunta.texto}"
    })
    
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
        db.add(MensajeChat(sesion_id=sesion.id, rol="user", texto=pregunta.texto))
        db.add(MensajeChat(sesion_id=sesion.id, rol="assistant", texto=full_text))
        db.commit()
    else:
        yield "[Neutral] Modo simulación (Sin API Key configurada)."

# ============================================================================
# 7. SINCRONIZACIÓN TEMARIO → BASE CONOCIMIENTO (Utilidad)
# ============================================================================

def sincronizar_temario_a_conocimiento(db: Session) -> int:
    """
    Sincroniza temas del Temario que aún no tienen bloques en BaseConocimiento.
    Crea un bloque básico con la descripción del tema.
    """
    temas = db.query(Temario).filter(Temario.activo == True).all()
    count = 0
    
    for tema in temas:
        existente = db.query(BaseConocimiento).filter(
            BaseConocimiento.temario_id == tema.id
        ).first()
        
        if not existente and tema.descripcion:
            vector = generar_embedding(db, f"[{tema.nombre}]: {tema.descripcion}")
            nuevo = BaseConocimiento(
                temario_id=tema.id,
                contenido=tema.descripcion,
                tipo_contenido="texto",
                orden_aparicion=1,
                pagina=tema.pagina_inicio or 0,
                ref_fuente=f"Temario - {tema.nombre}",
                embedding=vector,
                metadata_info={
                    "titulo": tema.nombre,
                    "nivel": tema.nivel,
                    "orden": tema.orden,
                    "origen": "sincronizacion"
                }
            )
            db.add(nuevo)
            count += 1
    
    db.commit()
    return count