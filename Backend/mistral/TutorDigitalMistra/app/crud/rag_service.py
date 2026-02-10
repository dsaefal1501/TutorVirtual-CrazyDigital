from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from app.models.modelos import BaseConocimiento, MensajeChat, SesionChat, Usuario, Temario
from app.schemas.schemas import PreguntaUsuario, RespuestaTutor, ConocimientoCreate
import os
import time
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

def generar_embedding(texto: str):
    """
    Genera el vector numérico para un texto usando Mistral.
    """
    if not client:
        # Fallback para pruebas si no hay API Key (retorna vector de ceros)
        return [0.0] * 1024 
    
    embeddings_batch_response = client.embeddings.create(
        model="mistral-embed",
        inputs=[texto],
    )
    return embeddings_batch_response.data[0].embedding

def buscar_contexto(db: Session, vector_pregunta: list) -> list[BaseConocimiento]:
    """
    Busca en la base de datos los 3 fragmentos más similares al vector de la pregunta.
    """
    # Usamos el operador de distancia coseno (<=>) de pgvector
    # Nota: Asegúrate de que la columna embedding en modelos.py sea Vector(1536)
    
    # Consulta usando SQLAlchemy 2.0 style
    stmt = select(BaseConocimiento).order_by(
        BaseConocimiento.embedding.cosine_distance(vector_pregunta)
    ).limit(3)
    
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

def _guardar_mensaje(db: Session, sesion_id: int, rol: str, texto: str):
    """
    Guarda un mensaje en el historial.
    """
    nuevo_mensaje = MensajeChat(
        sesion_id=sesion_id,
        rol=rol,
        texto=texto
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
    vector_pregunta = generar_embedding(pregunta.texto)
    contexto_docs = buscar_contexto(db, vector_pregunta)
    texto_contexto = "\n\n".join([f"- {doc.contenido}" for doc in contexto_docs])
    
    # 3. Datos del Usuario
    usuario = db.query(Usuario).filter(Usuario.id == pregunta.usuario_id).first()
    nombre_usuario = usuario.nombre if usuario else "Estudiante"
    
    # 4. Construir Prompt con Historial
    mensajes_llm = _recuperar_historial(db, sesion.id)
    
    instrucciones_emociones = (
        "IMPORTANTE: Inicia TU respuesta SIEMPRE con una de estas etiquetas de emoción que mejor se adapte al contenido: "
        "[Happy], [Thinking], [Angry], [Neutral], [Explaining]. "
        "Ejemplo: '[Happy] ¡Hola! Me alegra verte de nuevo.' o '[Explaining] Para resolver esto, primero...'"
    )

    prompt_con_contexto = f"{instrucciones_emociones}\n\nContexto RAG recuperado:\n{texto_contexto}\n\nPregunta del usuario ({nombre_usuario}): {pregunta.texto}"
    mensajes_llm.append({"role": "user", "content": prompt_con_contexto})

    # Guardar pregunta del usuario
    _guardar_mensaje(db, sesion.id, "user", pregunta.texto)

    # 5. Llamar al LLM (AGENT)
    respuesta_texto = ""
    if client:
        try:
            chat_response = client.agents.complete(
                agent_id=agent_id,
                messages=mensajes_llm,
            )
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
    vector_pregunta = generar_embedding(pregunta.texto)
    contexto_docs = buscar_contexto(db, vector_pregunta)
    texto_contexto = "\n\n".join([f"- {doc.contenido}" for doc in contexto_docs])

    usuario = db.query(Usuario).filter(Usuario.id == pregunta.usuario_id).first()
    nombre_usuario = usuario.nombre if usuario else "Estudiante"

    # 3. Historial
    mensajes_llm = _recuperar_historial(db, sesion.id)

    instrucciones_emociones = (
        "IMPORTANTE: Inicia TU respuesta SIEMPRE con una de estas etiquetas de emoción que mejor se adapte al contenido: "
        "[Happy], [Thinking], [Angry], [Neutral], [Explaining]. "
        "Ejemplo: '[Happy] ¡Claro que sí!' o '[Thinking] Déjame analizar eso...'"
    )

    prompt_con_contexto = f"{instrucciones_emociones}\n\nContexto RAG recuperado:\n{texto_contexto}\n\nPregunta del usuario ({nombre_usuario}): {pregunta.texto}"
    mensajes_llm.append({"role": "user", "content": prompt_con_contexto})

    # Guardar pregunta
    _guardar_mensaje(db, sesion.id, "user", pregunta.texto)

    # 4. Llamar al Agente en Streaming
    texto_completo_respuesta = ""
    
    if client:
        try:
            stream_response = client.agents.stream(
                agent_id=agent_id,
                messages=mensajes_llm,
            )
            
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
    vector_contenido = generar_embedding(datos.contenido)
    
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
        
        # 3. Generar Embedding
        vector = generar_embedding(contenido_texto)
        
        # 4. Guardar
        nuevo = BaseConocimiento(
            temario_id=tema.id,
            contenido=contenido_texto,
            embedding=vector,
            metadata_info={"origen": "migracion_automatica", "nivel": tema.nivel, "orden": tema.orden, "parent_id": tema.parent_id}
        )
        db.add(nuevo)
        count += 1
        
        # Rate Limit Mitigation: Esperar 1 segundo entre llamados a la API
        print(f"Procesado tema {tema.id} ({tema.nombre}). Esperando...")
        time.sleep(1)
    
    db.commit()
    return count

    def temalogico(db: Session):
         

      



