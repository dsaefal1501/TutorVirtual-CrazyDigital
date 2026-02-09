from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.modelos import BaseConocimiento, MensajeChat, SesionChat, Usuario, Temario
from app.schemas.schemas import PreguntaUsuario, RespuestaTutor
import os
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

def preguntar_al_tutor(db: Session, pregunta: PreguntaUsuario) -> RespuestaTutor:
    """
    Orquesta todo el flujo: Pregunta -> Embedding -> Búsqueda -> Prompt -> Respuesta
    """
    # 1. Generar Embedding
    vector_pregunta = generar_embedding(pregunta.texto)
    
    # 2. Buscar Contexto
    contexto_docs = buscar_contexto(db, vector_pregunta)
    
    # Unir el texto de los documentos encontrados
    texto_contexto = "\n\n".join([f"- {doc.contenido}" for doc in contexto_docs])
    
    # Variables de contexto temporal (Hasta que implementemos la búsqueda de usuario real)
    nombre_usuario = "Estudiante"
    nivel_usuario = "Principiante"
    tema_actual = "General"
    
    # 3. Construir el Prompt
    # Al usar un AGENT, su personalidad ya está definida en la plataforma de Mistral.
    # Solo le pasamos el contexto RAG y la pregunta.
    mensajes = [
        {"role": "user", "content": f"Contexto recuperado:\n{texto_contexto}\n\nPregunta del usuario ({nombre_usuario}, {nivel_usuario}, Temario: {tema_actual}): {pregunta.texto}"}
    ]

    # 4. Llamar al LLM (AGENT) para generar la respuesta
    if client:
        # Usamos el endpoint de Agentes
        chat_response = client.agents.complete(
            agent_id=agent_id,
            messages=mensajes,
        )
        respuesta_texto = chat_response.choices[0].message.content
    else:
        respuesta_texto = "[NEUTRAL] Error: No se configuró la API Key de Mistral. (Modo Simulación)"

    # 5. Guardar Logs/Historial (Opcional, pero recomendado)
    # Aquí podríamos guardar en SesionChat y MensajeChat
    
    return RespuestaTutor(
        sesion_id=pregunta.sesion_id or 0,
        respuesta=respuesta_texto,
        fuentes=[f"ID: {doc.id}" for doc in contexto_docs]
    )

def preguntar_al_tutor_stream(db: Session, pregunta: PreguntaUsuario):
    """
    Generador para streaming de respuesta (SSE) con PERSISTENCIA y MEMORIA.
    """
    # 0. Gestión de Sesión (Crear si no existe)
    if not pregunta.sesion_id:
        nueva_sesion = SesionChat(
            alumno_id=pregunta.usuario_id,
            titulo_resumen=pregunta.texto[:30] + "..." # Título temporal
        )
        db.add(nueva_sesion)
        db.commit()
        db.refresh(nueva_sesion)
        pregunta.sesion_id = nueva_sesion.id
        # IMPORTANTE: Enviar el ID de sesión primero para que el cliente sepa dónde seguir
        yield f"__SESION_ID__:{nueva_sesion.id}\n"

    # 1. Recuperar Historial de Chat (Memoria)
    historial_msgs = db.query(MensajeChat).filter(
        MensajeChat.sesion_id == pregunta.sesion_id
    ).order_by(MensajeChat.fecha.asc()).limit(10).all() # Últimos 10 mensajes

    # 2. Contexto Usuario
    usuario = db.query(Usuario).filter(Usuario.id == pregunta.usuario_id).first()
    nombre_usuario = usuario.nombre if usuario else "Estudiante"
    tema_actual = "General"
    nivel_usuario = "Principiante"
    
    # 3. Embedding y Búsqueda RAG
    vector_pregunta = generar_embedding(pregunta.texto)
    contexto_docs = buscar_contexto(db, vector_pregunta)
    texto_contexto = "\n\n".join([f"- {doc.contenido}" for doc in contexto_docs])

    # 4. Construir Mensajes para el Agente (System + History + RAG + User)
    mensajes_para_llm = []
    
    # a) Historial previo
    for msg in historial_msgs:
        role = "assistant" if msg.rol == "assistant" else "user"
        mensajes_para_llm.append({"role": role, "content": msg.texto})

    # b) Mensaje actual con RAG
    prompt_usuario = f"Contexto RAG recuperado:\n{texto_contexto}\n\nPregunta del usuario ({nombre_usuario}, {nivel_usuario}): {pregunta.texto}"
    mensajes_para_llm.append({"role": "user", "content": prompt_usuario})

    # 5. Guardar Pregunta del Usuario en DB
    msg_usuario = MensajeChat(
        sesion_id=pregunta.sesion_id,
        rol="user",
        texto=pregunta.texto,
        # embedding=vector_pregunta # Opcional: guardar embedding de la pregunta
    )
    db.add(msg_usuario)
    db.commit()

    # 6. Llamar al Agente en Streaming
    texto_completo_respuesta = ""
    
    if client:
        stream_response = client.agents.stream(
            agent_id=agent_id,
            messages=mensajes_para_llm,
        )
        
        for chunk in stream_response:
            content = chunk.data.choices[0].delta.content
            if content:
                texto_completo_respuesta += content
                yield content
    else:
        err_msg = "[NEUTRAL] Error: No API Key."
        texto_completo_respuesta = err_msg
        yield err_msg

    # 7. Guardar Respuesta del Agente en DB (una vez finalizado el stream)
    msg_asistente = MensajeChat(
        sesion_id=pregunta.sesion_id,
        rol="assistant", 
        texto=texto_completo_respuesta
    )
    db.add(msg_asistente)
    db.commit()
