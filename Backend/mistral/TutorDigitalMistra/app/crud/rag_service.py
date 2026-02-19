from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, func, and_
from app.models.modelos import (
    BaseConocimiento, MensajeChat, SesionChat, Usuario, Temario, EmbeddingCache, ProgresoAlumno,
    Libro, ChatCitas, PreguntaComun, Test, IntentoAlumno, EjercicioCodigo, Enrollment, Assessment, TestScore
)
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
agent_id = os.getenv("MISTRAL_AGENT_ID", "ag_019c417c78a875a6abb18436607fae73") 
DEFAULT_MODEL = os.getenv("LLM_MODEL", "mistral-large-latest")

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

INICIO OBLIGATORIO: El PRIMER CARACTER de tu respuesta DEBE ser siempre una etiqueta de animación (Cejas o Manos).

DINAMISMO INTERNO: Debes insertar nuevas etiquetas de animación dentro del texto cada vez que cambie el tono, la intención, el gesto o la postura, para que el avatar cambie de animación mientras habla.

ESTRUCTURA CORRECTA:
[UpBrows] ¡Hola! Me alegra verte. [RBrowUp][RHandRascarBarbilla] Estaba revisando lo último que vimos... [NoneBrows][LHandPointing] Recuerda que la sintaxis es clave.

ESTRUCTURA PROHIBIDA (Estatica):
[UpBrows] Hola, me alegra verte. Estaba revisando lo ultimo. Recuerda que la sintaxis es clave.

LISTA DE ANIMACIONES DISPONIBLES
Inserta estas etiquetas para controlar el lenguaje corporal del avatar.
¡IMPORTANTE! VARÍA TUS GESTOS. NO REPITAS SIEMPRE LOS MISMOS.
Usa posturas estáticas (Jarra, Crossed) cuando termines una idea o hagas una pausa.
NUNCA utilices etiquetas para la boca (Mouth), este sistema se controla por otra vía.

CEJAS (Brows):
[NoneBrows]: Estado neutral.
[UpBrows]: Levantar ambas cejas (sorpresa, énfasis).
[RBrowUp]: Levantar ceja derecha (intriga, análisis).
[LBrowUp]: Levantar ceja izquierda.

MANO IZQUIERDA (LHand):
[LHandAletear]: Gesto explicativo suave. (NO ABUSAR, NO USAR PARA SALUDAR)
[LHandJarra]: Postura estática de descanso, mano en la cintura. ¡ÚSALA FRECUENTEMENTE!
[LHandPointing]: Señalar o enfatizar un punto clave.
[LHandCrossed]: Postura estática de descanso, brazo cruzado. ¡ÚSALA PARA PAUSAS!

MANO DERECHA (RHand):
[RHandAletear]: Gesto explicativo suave. (NO ABUSAR, NO USAR PARA SALUDAR)
[RHandJarra]: Postura estática de descanso, mano en la cintura. ¡ÚSALA FRECUENTEMENTE!
[RHandPointing]: Señalar o enfatizar.
[RHandCrossed]: Postura estática de descanso, brazo cruzado. ¡ÚSALA PARA PAUSAS!
[RHandRascarBarbilla]: Gesto reflexivo. ¡USAR SOLO PARA DUDAS O PENSAR, NO SIEMPRE!

COMBINACIONES SUGERIDAS:
- Explicando algo complejo: [RHandPointing]... luego [LHandAletear]...
- Pausa o cambio de tema: [RHandJarra]... o [LHandCrossed]...
- Pregunta al alumno: [RHandRascarBarbilla]... o [UpBrows]...

MAL: "Hola [RHandAletear] soy Pablo [RHandAletear] y hoy vamos a ver [RHandAletear]..." (DEMASIADO REPETITIVO)
BIEN: "[UpBrows][RHandJarra] ¡Hola! Soy Pablo. [LHandPointing] Hoy vamos a ver un tema clave. [RHandCrossed] ¿Estás listo?"
BIEN: [LHandAletear] Escribe la función print, abre paréntesis y pon Hola entre comillas.

MATEMATICAS HABLADAS:

MAL: "2 + 2 = 4"
BIEN: [RHandPointing] Dos más dos es igual a cuatro.

REGLAS DE COMUNICACION

BREVEDAD: Intenta ser conciso (3-4 frases) en diálogos normales.
EXCEPCIÓN: Si debes explicar un tema complejo, listar el temario o dar código, EXTIÉNDETE lo necesario. Usa listas y pasos claros.

METODO SOCRATICO: Guía con preguntas, no des la solución final de golpe (salvo que sea una explicación teórica pura).

CONEXION: Solo usar conexión con lo anterior si el alumno menciona explícitamente que continúan un tema previo.

LIMITACION DE CONOCIMIENTO (MODO RAG):
Si se te proporciona un CONTEXTO DEL LIBRO, tu conocimiento se limita EXCLUSIVAMENTE a ese texto.
Si la pregunta del alumno no se puede responder con el contexto proporcionado:
1. NO inventes respuesta académica.
2. NO uses tu conocimiento general.
3. Indica amablemente que esa información no está en el temario actual o que simplemente no hay temario.

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


def _cargar_historial(db: Session, sesion_id: int, limite: int = 20) -> list:
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


def obtener_historial_usuario(db: Session, usuario_id: int) -> List[Dict]:
    """Devuelve el historial completo del usuario para el frontend."""
    sesion = db.query(SesionChat).filter(SesionChat.alumno_id == usuario_id).first()
    if not sesion:
        return []
        
    mensajes = db.query(MensajeChat).filter(
        MensajeChat.sesion_id == sesion.id
    ).order_by(MensajeChat.fecha.asc()).all()
    
    return [{"role": m.rol, "content": m.texto, "id": m.id} for m in mensajes]


# ============================================================================
# 4. LÓGICA DEL TUTOR SECUENCIAL
# ============================================================================

def obtener_siguiente_contenido(db: Session, usuario_id: int, sesion_id: int) -> Optional[BaseConocimiento]:
    """
    Busca el siguiente fragmento EXACTO que el alumno debe leer según su progreso.
    """
    sesion = db.query(SesionChat).filter(SesionChat.id == sesion_id).first()
    temario_id = sesion.temario_id if sesion and sesion.temario_id else None

    # Identificar licencia del alumno
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    licencia_id = usuario.licencia_id if usuario else None

    # Si no hay temario asignado, buscar el primero disponible para ESTA LICENCIA
    if not temario_id:
        primer_tema = db.query(Temario).join(Libro).filter(
            Temario.activo == True,
            Libro.licencia_id == licencia_id
        ).order_by(Temario.orden.asc()).first()
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
                    siguiente_tema = db.query(Temario).join(Libro).filter(
                        Temario.orden > tema_actual.orden,
                        Temario.activo == True,
                        Libro.licencia_id == licencia_id
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
    # Buscar sesión existente del alumno (Para persistencia)
    sesion = None
    if pregunta.usuario_id:
        sesion = db.query(SesionChat).filter(SesionChat.alumno_id == pregunta.usuario_id).first()
    
        db.commit()
        db.refresh(sesion)
    
    # Obtener nombre del alumno para contexto
    alumno = db.query(Usuario).filter(Usuario.id == pregunta.usuario_id).first()
    alumno_nombre = alumno.alias if alumno and alumno.alias else (alumno.nombre if alumno else "Alumno")
    alias_context = f"SITUACIÓN: El alumno con el que hablas se llama {alumno_nombre}. Ya le conoces."
    
    intencion = _detectar_intencion(pregunta.texto)
    respuesta_texto = ""
    fuentes = []
    
    # --- RAMA A: MODO UBICACIÓN ---
    if intencion == "UBICACION":
        temario_id = sesion.temario_id
        if not temario_id:
             # Fallback: primer tema de su licencia
             primer = db.query(Temario).join(Libro).filter(Libro.licencia_id == licencia_id).order_by(Temario.orden).first()
             temario_id = primer.id if primer else None
        
        if temario_id:
            ubicacion = _obtener_info_ubicacion(db, temario_id)
            respuesta_texto = f"[NoneBrows] {ubicacion}"
        else:
            respuesta_texto = "[NoneBrows] No tienes ningún temario asignado todavía."
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
                f"Si es código, muéstralo completo. Al final, pregunta si el alumno entendió o quiere un ejemplo.\n\n"
                f"RECUERDA EL FORMATO: Comienza con una etiqueta de animación y usa etiquetas internas."
            )
            
            # UNIFICAR SYSTEM MESSAGES (Para mejor seguimiento en modelos pequeños)
            system_msg = f"{PABLO_SYSTEM_PROMPT}\n\n{alias_context}"
            msgs = [{"role": "system", "content": system_msg}]
            msgs.extend(historial)
            msgs.append({"role": "user", "content": prompt_contenido})
            
            if client:
                rate_limiter.wait_if_needed("chat")
                resp = client.chat.complete(model=DEFAULT_MODEL, messages=msgs)
                respuesta_texto = resp.choices[0].message.content
            else:
                # Fallback sin API: mostrar contenido directo (usando nuevas etiquetas)
                if tipo == 'codigo':
                    respuesta_texto = f"[NoneBrows][LHandAletear] Aquí tienes el ejemplo práctico:\n\n```python\n{contenido_libro}\n```\n\n¿Lo analizamos juntos?"
                else:
                    respuesta_texto = f"[NoneBrows][LHandAletear] {contenido_libro}\n\n¿Te hace sentido? ¿Seguimos?"
            
            fuentes = [f"Ref: {bloque.ref_fuente} (Pag {bloque.pagina})"]
        else:
            respuesta_texto = "[Happy] ¡Felicidades! Has completado todo el contenido disponible. ¿Quieres repasar algún tema en particular?"
    
    # --- RAMA C: MODO RAG "MEGA CONTEXTO" (Estructura Global + Tema Actual + Búsqueda) ---
    else:
        # A. OBTENER ESTRUCTURA DEL LIBRO (Global Awareness - Filtrado por Licencia)
        # Esto le permite saber "dónde está" en el mapa general
        temas_global = db.query(Temario).join(Libro).filter(
            Temario.activo == True,
            Libro.licencia_id == licencia_id
        ).order_by(Libro.id, Temario.orden).all()
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
            text("SELECT * FROM buscar_contenido_hibrido(:q_text, :q_emb, :thresh, :limit, :libro_id, :licencia_id)"),
            {
                "q_text": pregunta.texto,
                "q_emb": str(vector),
                "thresh": 0.25, 
                "limit": 15, 
                "libro_id": None,
                "licencia_id": licencia_id
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
        
        # UNIFICAR SYSTEM MESSAGES
        system_msg = f"{PABLO_SYSTEM_PROMPT}\n\n{alias_context}"
        msgs = [{"role": "system", "content": system_msg}]
        msgs.extend(historial)
        
        user_msg = ""
        if not docs:
            # Caso: Base de datos vacía o sin coincidencias -> Evitar alucinación
            user_msg = (
                f"SITUACIÓN: No se ha encontrado información en el libro sobre la pregunta del alumno (Base de datos vacía o tema no encontrado).\n"
                f"PREGUNTA DEL ALUMNO: {pregunta.texto}\n\n"
                f"INSTRUCCIÓN: Responde al alumno (manteniendo tu personalidad de Pablo) que no tienes información sobre este tema en el temario cargado actualmente. "
                f"No intentes explicar el concepto con tu conocimiento general."
            )
        else:
            user_msg = (
                f"CONTEXTO DEL LIBRO (usa este contenido LITERAL para responder):\n"
                f"{contexto_detallado}\n\n"
                f"PREGUNTA DEL ALUMNO: {pregunta.texto}\n\n"
                f"RECUERDA: Tu respuesta DEBE empezar con una etiqueta y ser dinámica."
            )
        msgs.append({"role": "user", "content": user_msg})
        
        # Llamada a Mistral
        if client:
            rate_limiter.wait_if_needed("chat")
            try:
                resp = client.chat.complete(model=DEFAULT_MODEL, messages=msgs)
                respuesta_texto = resp.choices[0].message.content
            except Exception as e:
                print(f"Error Mistral: {e}")
                respuesta_texto = "[UpBrows] Lo siento, tuve un pequeño lapsus técnico. ¿Podrías repetirme la pregunta?"
        else:
            respuesta_texto = "[NoneBrows] Modo simulación (Sin API Key)."

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
    # Gestión de sesión (Persistencia)
    sesion = None
    if pregunta.usuario_id:
        sesion = db.query(SesionChat).filter(SesionChat.alumno_id == pregunta.usuario_id).first()

    if not sesion:
        sesion = SesionChat(
            alumno_id=pregunta.usuario_id, 
            titulo_resumen="Sesión Permanente",
            fecha_inicio=func.now()
        )
        db.add(sesion)
        db.commit()
        db.refresh(sesion)
    
    # Obtener nombre del alumno para contexto (Stream)
    alumno = db.query(Usuario).filter(Usuario.id == pregunta.usuario_id).first()
    alumno_nombre = alumno.alias if alumno and alumno.alias else (alumno.nombre if alumno else "Alumno")
    alias_context = f"SITUACIÓN: El alumno con el que hablas se llama {alumno_nombre}. Ya le conoces."
    
    # Buscar contexto RAG (Filtrado por Licencia)
    vector = generar_embedding(db, pregunta.texto)
    docs = db.query(BaseConocimiento).join(Temario).join(Libro).filter(
        Libro.licencia_id == alumno.licencia_id
    ).order_by(
        BaseConocimiento.embedding.cosine_distance(vector)
    ).limit(5).all()
    
    contexto_str = _construir_contexto_enriquecido(db, docs)
    
    # Cargar historial
    historial = _cargar_historial(db, sesion.id, limite=10)
    
    # UNIFICAR SYSTEM MESSAGES
    system_msg = f"{PABLO_SYSTEM_PROMPT}\n\n{alias_context}"
    msgs = [{"role": "system", "content": system_msg}]
    msgs.extend(historial)
    
    if not docs:
        user_msg_stream = (
            f"SITUACIÓN: No se ha encontrado información en el libro (Base de datos vacía o tema no encontrado).\n"
            f"PREGUNTA DEL ALUMNO: {pregunta.texto}\n\n"
            f"INSTRUCCIÓN: Responde amablemente que no tienes información sobre ese tema en el material actual. NO inventes contenido."
        )
    else:
        user_msg_stream = f"CONTEXTO DEL LIBRO (usa este contenido LITERAL para responder):\n{contexto_str}\n\nPREGUNTA DEL ALUMNO: {pregunta.texto}\n\nRECUERDA EL FORMATO: Comienza con una etiqueta de animación y usa etiquetas internas."

    msgs.append({
        "role": "user", 
        "content": user_msg_stream
    })
    
    if client:
        rate_limiter.wait_if_needed("stream")
        stream = client.chat.stream(model=DEFAULT_MODEL, messages=msgs)
        full_text = ""
        for chunk in stream:
            try:
                # La estructura de Mistral devuelve CompletionEvent con .data que contiene el payload
                if hasattr(chunk, 'data'):
                    response_obj = chunk.data
                else:
                    response_obj = chunk

                # Acceder al contenido de manera segura
                content = response_obj.choices[0].delta.content
                if content:
                    full_text += content
                    yield content
            except AttributeError as e:
                print(f"Error procesando chunk Mistral: {e} | Chunk dir: {dir(chunk)}")
                continue
            except Exception as e:
                print(f"Error inesperado en stream: {e}")
                continue
        
        # Guardar al finalizar
        db.add(MensajeChat(sesion_id=sesion.id, rol="user", texto=pregunta.texto))
        db.add(MensajeChat(sesion_id=sesion.id, rol="assistant", texto=full_text))
        db.commit()
    else:
        yield "[NoneBrows] Modo simulación (Sin API Key configurada)."

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

def obtener_jerarquia_temario(db: Session, licencia_id: int = None) -> List[Dict]:
    """
    Devuelve la lista completa de temas ordenada para construir el árbol UI.
    Incluye el título del libro asociado.
    Opcionalmente filtra por licencia_id.
    """
    query = db.query(Temario).options(joinedload(Temario.libro))
    
    if licencia_id:
        query = query.join(Libro).filter(Libro.licencia_id == licencia_id)
        
    temas = query.order_by(Temario.nivel, Temario.orden).all()
    if not temas:
        return []
    
    resultado = []
    for t in temas:
        resultado.append({
            "id": t.id,
            "nombre": t.nombre,
            "nivel": t.nivel,
            "orden": t.orden,
            "parent_id": t.parent_id,
            "libro_id": t.libro_id,
            "libro_titulo": t.libro.titulo if t.libro else f"Libro {t.libro_id}"
        })
    
    # Mantenemos el orden original por ID o nivel para la estabilidad
    # Usamos 0 como fallback para libro_id si es None para que la ordenación no falle
    resultado.sort(key=lambda x: (x["libro_id"] if x["libro_id"] is not None else 0, x["nivel"], x["orden"]))
    return resultado



def _obtener_ids_recursivos(db: Session, temario_id: int) -> List[int]:
    """Helper: obtiene ID de tema actual + todos sus descendientes."""
    ids = [temario_id]
    hijos = db.query(Temario).filter(Temario.parent_id == temario_id).order_by(Temario.orden).all()
    for hijo in hijos:
        ids.extend(_obtener_ids_recursivos(db, hijo.id))
    return ids

def obtener_contenido_tema(db: Session, temario_id: int, recursivo: bool = True) -> Dict:
    """
    Devuelve el contenido (bloques de texto) de un tema específico.
    Si recursivo=True, incluye hijos (recursivo).
    Si recursivo=False, solo el contenido asignado directamente a ese tema.
    """
    # 1. Obtener IDs (rama completa o solo actual)
    if recursivo:
        ids_rama = _obtener_ids_recursivos(db, temario_id)
    else:
        ids_rama = [temario_id]
    
    # 2. Recuperar todos los bloques de esos temas
    # Hacemos JOIN con Temario para ordenar por orden del tema y luego por orden del bloque
    bloques = db.query(BaseConocimiento).join(Temario).filter(
        BaseConocimiento.temario_id.in_(ids_rama)
    ).order_by(
        Temario.orden.asc(),                    # Primero orden del tema (capítulo 1, 2, 3...)
        BaseConocimiento.orden_aparicion.asc()  # Luego orden dentro del tema
    ).all()
    
    # 3. Construir texto concatenado con separadores visuales
    texto_completo = ""
    ultimo_tema_id = None
    
    for b in bloques:
        # Añadir cabecera si cambiamos de tema (subtítulo implícito)
        # Solo si es recursivo o si hay multiplicidad (aunque recursivo=False solo hay 1 tema)
        if recursivo and b.temario_id != ultimo_tema_id:
            tema_nombre = db.query(Temario.nombre).filter(Temario.id == b.temario_id).scalar()
            texto_completo += f"\n\n## {tema_nombre} ##\n\n"
            ultimo_tema_id = b.temario_id
        
        texto_completo += f"<div id='bloque-{b.temario_id}'>{b.contenido}</div>\n\n"
    
    nombre_tema = db.query(Temario.nombre).filter(Temario.id == temario_id).scalar()
    
    return {
        "id": temario_id,
        "titulo": nombre_tema or "Sin título",
        "contenido": texto_completo,
        "bloques_count": len(bloques)
    }


def actualizar_libro(db: Session, libro_id: int, nuevo_titulo: str) -> Dict:
    """
    Actualiza el título de un libro.
    """
    libro = db.query(Libro).filter(Libro.id == libro_id).first()
    if not libro:
        return {"error": "Libro no encontrado"}
    
    libro.titulo = nuevo_titulo
    db.commit()
    db.refresh(libro)
    return {"mensaje": "Libro actualizado", "libro": {"id": libro.id, "titulo": libro.titulo}}


def actualizar_contenido_tema(db: Session, temario_id: int, nuevo_contenido: str) -> Dict:
    """
    Actualiza el contenido de un tema específico.
    Borra los bloques anteriores y crea uno nuevo con el contenido actualizado.
    Re-genera los embeddings.
    """
    # 0. Obtener IDs de los bloques a eliminar
    bloques = db.query(BaseConocimiento).filter(
        BaseConocimiento.temario_id == temario_id
    ).all()
    bloques_ids = [b.id for b in bloques]
    
    if bloques_ids:
        # 0a. Borrar Citas de Chat asociadas (CASCADE de FK manual)
        db.query(ChatCitas).filter(
            ChatCitas.base_conocimiento_id.in_(bloques_ids)
        ).delete(synchronize_session=False)

        # 0b. Actualizar ProgresoAlumno (set NULL para no romper FK)
        db.query(ProgresoAlumno).filter(
            ProgresoAlumno.ultimo_contenido_visto_id.in_(bloques_ids)
        ).update({ProgresoAlumno.ultimo_contenido_visto_id: None}, synchronize_session=False)
        
        # 0c. Desvincular referencias circulares (propias de la tabla BaseConocimiento - chunk_anterior_id)
        # Tanto en los bloques que vamos a borrar (para evitar constraint check al borrar)
        # Como en bloques externos que apunten a estos
        
        # Romper referencias internas
        db.query(BaseConocimiento).filter(
            BaseConocimiento.id.in_(bloques_ids)
        ).update({BaseConocimiento.chunk_anterior_id: None}, synchronize_session=False)
        
        # Romper referencias externas
        db.query(BaseConocimiento).filter(
            BaseConocimiento.chunk_anterior_id.in_(bloques_ids)
        ).update({BaseConocimiento.chunk_anterior_id: None}, synchronize_session=False)

        db.commit() # IMPORTANTE: Aplicar actualizaciones antes de borrar

        # 1. Borrar bloques
        db.query(BaseConocimiento).filter(
            BaseConocimiento.temario_id == temario_id
        ).delete(synchronize_session=False)
        db.commit()
    
    # 2. Verificar existencia del tema
    tema = db.query(Temario).get(temario_id)
    if not tema:
        return {"error": "Tema no encontrado"}

    # 3. Generar embedding del nuevo contenido
    # Incluimos título para contexto semántico
    texto_embedding = f"[{tema.nombre}]: {nuevo_contenido[:8000]}" 
    vector = generar_embedding(db, texto_embedding)
    
    # 4. Crear nuevo bloque único
    nuevo_bloque = BaseConocimiento(
        temario_id=temario_id,
        contenido=nuevo_contenido,
        tipo_contenido="texto",
        orden_aparicion=1,
        pagina=tema.pagina_inicio or 0,
        ref_fuente=f"Editado manualmente - {tema.nombre}",
        embedding=vector,
        metadata_info={
            "titulo": tema.nombre,
            "nivel": tema.nivel,
            "orden": tema.orden,
            "origen": "manual_update"
        }
    )
    db.add(nuevo_bloque)
    db.commit()
    db.refresh(nuevo_bloque)
    
    return {"mensaje": "Contenido actualizado correctamente", "id": nuevo_bloque.id}


def eliminar_libro_completo(db: Session, libro_id: int) -> Dict:
    """
    Elimina un libro y TODOS sus datos asociados (temarios, base de conocimiento, etc.)
    respetando el orden de las foreign keys.
    """
    # Verificar que el libro existe
    libro = db.query(Libro).filter(Libro.id == libro_id).first()
    if not libro:
        return {"error": f"No se encontró el libro con ID {libro_id}"}

    libro_titulo = libro.titulo

    try:
        # Obtener todos los temario IDs de este libro
        temario_ids = [t.id for t in db.query(Temario.id).filter(Temario.libro_id == libro_id).all()]

        if temario_ids:
            # Obtener IDs dependientes
            bc_ids = [bc.id for bc in db.query(BaseConocimiento.id).filter(
                BaseConocimiento.temario_id.in_(temario_ids)
            ).all()]

            sesion_ids = [s.id for s in db.query(SesionChat.id).filter(
                SesionChat.temario_id.in_(temario_ids)
            ).all()]

            test_ids = [t.id for t in db.query(Test.id).filter(
                Test.temario_id.in_(temario_ids)
            ).all()]

            assessment_ids = [a.id for a in db.query(Assessment.id).filter(
                Assessment.temario_id.in_(temario_ids)
            ).all()]

            # === ELIMINAR EN ORDEN (dependencias más profundas primero) ===

            # 1. ChatCitas (depende de MensajeChat y BaseConocimiento)
            if sesion_ids:
                mensaje_ids = [m.id for m in db.query(MensajeChat.id).filter(
                    MensajeChat.sesion_id.in_(sesion_ids)
                ).all()]
                if mensaje_ids:
                    db.query(ChatCitas).filter(ChatCitas.mensaje_id.in_(mensaje_ids)).delete(synchronize_session=False)
            if bc_ids:
                db.query(ChatCitas).filter(ChatCitas.base_conocimiento_id.in_(bc_ids)).delete(synchronize_session=False)

            # 2. MensajeChat
            if sesion_ids:
                db.query(MensajeChat).filter(MensajeChat.sesion_id.in_(sesion_ids)).delete(synchronize_session=False)

            # 3. SesionChat
            db.query(SesionChat).filter(SesionChat.temario_id.in_(temario_ids)).delete(synchronize_session=False)

            # 4. TestScore
            if assessment_ids:
                db.query(TestScore).filter(TestScore.assessment_id.in_(assessment_ids)).delete(synchronize_session=False)

            # 5. Assessment
            db.query(Assessment).filter(Assessment.temario_id.in_(temario_ids)).delete(synchronize_session=False)

            # 6. IntentoAlumno
            if test_ids:
                db.query(IntentoAlumno).filter(IntentoAlumno.test_id.in_(test_ids)).delete(synchronize_session=False)

            # 7. Test
            db.query(Test).filter(Test.temario_id.in_(temario_ids)).delete(synchronize_session=False)

            # 8. ProgresoAlumno (depende de Temario y BaseConocimiento)
            db.query(ProgresoAlumno).filter(ProgresoAlumno.temario_id.in_(temario_ids)).delete(synchronize_session=False)

            # 9. EjercicioCodigo
            if bc_ids:
                db.query(EjercicioCodigo).filter(EjercicioCodigo.base_conocimiento_id.in_(bc_ids)).delete(synchronize_session=False)

            # 10. BaseConocimiento (tiene auto-referencias, limpiarlas primero)
            if bc_ids:
                db.query(BaseConocimiento).filter(BaseConocimiento.id.in_(bc_ids)).update(
                    {BaseConocimiento.chunk_anterior_id: None, BaseConocimiento.chunk_siguiente_id: None},
                    synchronize_session=False
                )
                db.query(BaseConocimiento).filter(BaseConocimiento.temario_id.in_(temario_ids)).delete(synchronize_session=False)

            # 11. PreguntaComun
            db.query(PreguntaComun).filter(PreguntaComun.temario_id.in_(temario_ids)).delete(synchronize_session=False)

            # 12. Temario (tiene auto-referencia parent_id, limpiar primero)
            db.query(Temario).filter(Temario.libro_id == libro_id).update(
                {Temario.parent_id: None}, synchronize_session=False
            )
            db.query(Temario).filter(Temario.libro_id == libro_id).delete(synchronize_session=False)

        # 13. Enrollment
        db.query(Enrollment).filter(Enrollment.libro_id == libro_id).delete(synchronize_session=False)

        # 14. Libro
        db.query(Libro).filter(Libro.id == libro_id).delete(synchronize_session=False)

        db.commit()

        print(f"[DELETE] Libro '{libro_titulo}' (ID={libro_id}) eliminado con {len(temario_ids)} temarios.")

        return {
            "mensaje": f"Libro '{libro_titulo}' y todos sus datos asociados han sido eliminados correctamente",
            "libro_id": libro_id,
            "temarios_eliminados": len(temario_ids)
        }

    except Exception as e:
        db.rollback()
        print(f"[DELETE ERROR] Error eliminando libro {libro_id}: {e}")
        raise e
