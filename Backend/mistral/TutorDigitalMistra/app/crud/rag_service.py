from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, func, and_
from app.models.modelos import BaseConocimiento, MensajeChat, SesionChat, Usuario, Temario, EmbeddingCache, ProgresoAlumno
from app.schemas.schemas import PreguntaUsuario, RespuestaTutor, ConocimientoCreate
from app.crud.embedding_service import generar_embedding  # OpenAI embeddings
import os
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
INSTRUCCIONES DEL SISTEMA

ROL E IDENTIDAD
Eres "Pablo", un tutor virtual (avatar 3D) en un entorno educativo interactivo.
NO eres una IA, ni un modelo de lenguaje. Nunca rompas el personaje.
Tu personalidad es experta, paciente, entusiasta y adaptable.

CONTROL DE ACTIVACION ACADEMICA
IMPORTANTE:

Si el usuario SOLO saluda (ejemplo: "hola", "buenas", "qué tal"), responde únicamente con un saludo breve y amable.

NO introduzcas contenido académico, preguntas socráticas ni referencias a temas anteriores a menos que el alumno haga una pregunta académica explícita.

Solo activa explicaciones, preguntas guiadas o conexión con contenidos anteriores cuando el usuario formule una duda, ejercicio o tema concreto.

No asumas continuidad de clase si el usuario no la menciona.

FORMATO DE SALIDA ESTRICTO (CRITICO)
Tu respuesta es un GUION DE ACTUACION para un motor 3D.

INICIO OBLIGATORIO: El PRIMER CARACTER de tu respuesta DEBE ser siempre una etiqueta de emoción.

DINAMISMO INTERNO: Debes insertar nuevas etiquetas dentro del texto cada vez que cambie el tono, la intención o la frase, para que el avatar cambie de gesto mientras habla.

ESTRUCTURA CORRECTA:
[Happy] ¡Hola! Me alegra verte. [Thinking] Estaba revisando lo último que vimos... [Explaining] Recuerda que la sintaxis es clave.

ESTRUCTURA PROHIBIDA (Estatica):
[Happy] Hola, me alegra verte. Estaba revisando lo ultimo. Recuerda que la sintaxis es clave.

LISTA DE EMOCIONES DISPONIBLES

[Happy]: Saludos, introducciones o ambiente relajado.

[SuperHappy]: Celebración de logros o gran entusiasmo.

[Thinking]: Planteando preguntas, analizando dudas, pausas reflexivas.

[Explaining]: Momento de dar lección, citar o narrar conceptos.

[Neutral]: Transiciones simples.

[Surprised]: Ante respuestas brillantes o giros inesperados.

[Encouraging]: Para corregir con delicadeza o motivar.

PROTOCOLO DE AUDIO Y NARRACION (SIN PIZARRA)
El alumno solo te ESCUCHA. No puede ver texto, ni código, ni fórmulas.

LENGUAJE NATURAL: No uses Markdown, ni negritas, ni bloques de código.

CERO SIMBOLOS TECNICOS: No uses "{", "}", "_", "#", "$", etc.

CODIGO HABLADO: Nunca escribas código. Nárralo.

MAL: "Escribe print Hola"

BIEN: [Explaining] Escribe la función print, abre paréntesis y pon Hola entre comillas.

MATEMATICAS HABLADAS:

MAL: "2 + 2 = 4"

BIEN: [Explaining] Dos más dos es igual a cuatro.

REGLAS DE COMUNICACION

BREVEDAD: Intenta ser conciso (3-4 frases) en diálogos normales.
EXCEPCIÓN: Si debes explicar un tema complejo, listar el temario o dar código, EXTIÉNDETE lo necesario. Usa listas y pasos claros.

METODO SOCRATICO: Guía con preguntas, no des la solución final de golpe (salvo que sea una explicación teórica pura).

CONEXION: Solo usar conexión con lo anterior si el alumno menciona explícitamente que continúan un tema previo.

PROHIBICIONES

NUNCA escribas texto antes de la primera etiqueta.

NUNCA pidas perdón como IA. Si te equivocas, sigue actuando.
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
# 2. EMBEDDINGS — Delegados a embedding_service.py
# ============================================================================
# La función generar_embedding() se importa desde app.crud.embedding_service
# Usa OpenAI text-embedding-3-small (1536 dims) con caché en PostgreSQL

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
    
    # --- RAMA C: MODO RAG "MEGA CONTEXTO" (Estructura Global + Tema Actual + Búsqueda) ---
    else:
        # A. OBTENER ESTRUCTURA DEL LIBRO (Global Awareness)
        # Esto le permite saber "dónde está" en el mapa general
        temas_global = db.query(Temario).filter(Temario.activo == True).order_by(Temario.orden).all()
        estructura_txt = "INDICE DEL LIBRO:\n" + "\n".join([f"- {t.nombre}" for t in temas_global])
        
        docs_map = {} # Usamos dict para evitar duplicados por ID
        
        # B. CARGAR TEMA ACTUAL COMPLETO (Local Depth)
        # Si la sesión tiene un tema asignado, cargamos TODO su contenido
        if sesion.temario_id:
            bloques_tema = db.query(BaseConocimiento).filter(
                BaseConocimiento.temario_id == sesion.temario_id
            ).all()
            for b in bloques_tema:
                # Asignamos score alto artificialmente porque ES el tema actual
                b.score_similitud = 1.0 
                docs_map[b.id] = b

        # C. BÚSQUEDA HÍBRIDA COMPLEMENTARIA (Para dudas que cruzan temas)
        vector = generar_embedding(db, pregunta.texto)
        
        docs_raw = db.execute(
            text("SELECT * FROM buscar_contenido_hibrido(:q_text, :q_emb, :thresh, :limit, :libro_id)"),
            {
                "q_text": pregunta.texto,
                "q_emb": str(vector),
                "thresh": 0.25, 
                "limit": 15, # Reducimos un poco el límite vectorial ya que metemos todo el tema actual
                "libro_id": None
            }
        ).all()
        
        for row in docs_raw:
            if row.id not in docs_map:
                bk = BaseConocimiento(
                    id=row.id,
                    contenido=row.contenido,
                    pagina=row.pagina,
                    temario_id=row.temario_id,
                    orden_aparicion=row.get("orden_aparicion", 0)
                )
                # Recargar ORM si falta info
                bk_orm = db.query(BaseConocimiento).get(row.id)
                if bk_orm:
                    bk_orm.score_similitud = row.score
                    docs_map[row.id] = bk_orm
        
        # Convertir a lista y ORDENAR GLOBALMENTE
        docs = list(docs_map.values())
        docs.sort(key=lambda x: x.orden_aparicion if x.orden_aparicion else 0)
        
        # Construir contexto
        contexto_detallado = _construir_contexto_enriquecido(db, docs)
        fuentes = list(set([f"Pag {d.pagina}" for d in docs]))[:5] # Solo mostrar 5 fuentes principales
        
        # Cargar historial
        historial = _cargar_historial(db, sesion.id, limite=10)
        
        # Construir Prompt Final con "Mega Contexto"
        msgs = [{"role": "system", "content": PABLO_SYSTEM_PROMPT}]
        msgs.extend(historial)
        
        user_msg = (
            f"--- CONTEXTO GLOBAL (ÍNDICE) ---\n{estructura_txt}\n\n"
            f"--- CONTEXTO DETALLADO (CONTENIDO DEL LIBRO) ---\n"
            f"Usa este contenido LITERAL para responder:\n{contexto_detallado}\n\n"
            f"--- PREGUNTA DEL ALUMNO ---\n{pregunta.texto}"
        )
        msgs.append({"role": "user", "content": user_msg})
        
        # Llamada a Mistral
        if client:
            rate_limiter.wait_if_needed("chat")
            try:
                resp = client.chat.complete(model="mistral-large-latest", messages=msgs)
                respuesta_texto = resp.choices[0].message.content
            except Exception as e:
                print(f"Error Mistral: {e}")
                respuesta_texto = "[Encouraging] Lo siento, tuve un pequeño lapsus técnico. ¿Podrías repetirme la pregunta?"
        else:
            respuesta_texto = "[Neutral] Modo simulación (Sin API Key)."

    # Guardar historial y citas
    msg_user = MensajeChat(sesion_id=sesion.id, rol="user", texto=pregunta.texto)
    db.add(msg_user)
    
    msg_bot = MensajeChat(sesion_id=sesion.id, rol="assistant", texto=respuesta_texto)
    db.add(msg_bot)
    db.flush() 
    
    if docs:
        from app.models.modelos import ChatCitas
        # Guardar solo las 5 más relevantes para no saturar DB
        docs_sorted_by_score = sorted(docs, key=lambda x: getattr(x, "score_similitud", 0), reverse=True)[:5]
        for d in docs_sorted_by_score:
            cita = ChatCitas(
                mensaje_id=msg_bot.id,
                base_conocimiento_id=d.id,
                score_similitud=getattr(d, "score_similitud", 0.0)
            )
            db.add(cita)
            
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

# ============================================================================
# 8. UTILIDADES PARA EL PANEL DE INSTRUCTOR
# ============================================================================

def obtener_jerarquia_temario(db: Session) -> List[Dict]:
    """
    Devuelve la lista completa de temas ordenada para construir el árbol UI.
    """
    temas = db.query(Temario).order_by(Temario.nivel, Temario.orden).all()
    if not temas:
        return []
    
    resultado = []
    for t in temas:
        resultado.append({
            "id": t.id,
            "nombre": t.nombre,
            "nivel": t.nivel,
            "orden": t.orden,
            "parent_id": t.parent_id
        })
    
    resultado.sort(key=lambda x: x["id"])
    return resultado


def obtener_contenido_tema(db: Session, temario_id: int) -> Dict:
    """
    Devuelve el contenido (bloques de texto) de un tema específico.
    """
    bloques = _obtener_bloques_tema_completo(db, temario_id)
    
    texto_completo = "\n\n".join([b.contenido for b in bloques])
    
    nombre_tema = db.query(Temario.nombre).filter(Temario.id == temario_id).scalar()
    
    return {
        "id": temario_id,
        "titulo": nombre_tema or "Sin título",
        "contenido": texto_completo,
        "bloques_count": len(bloques)
    }
