from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.db.database import get_db, engine
from app.models import modelos
from app.schemas.schemas import PreguntaUsuario, RespuestaTutor
from app.crud import rag_service
from app.crud import ingest_service
from elevenlabs.client import ElevenLabs

# Crear las tablas automáticamente
modelos.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Tutor Digital API",
    description="API para interactuar con el Tutor Digital basado en RAG y Mistral",
    version="1.0.0",
)

client = ElevenLabs(api_key="sk_401a61fdf35cc545e1ab166b94c1de3ff4ba767d946d6ec2")

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"mensaje": "Bienvenido a la API del Tutor Digital"}

@app.post("/ask", response_model=RespuestaTutor)
def ask_tutor(pregunta: PreguntaUsuario, db: Session = Depends(get_db)):
    """
    Endpoint principal para preguntar al tutor.
    """
    try:
        if not pregunta.texto:
            raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía")
                
        respuesta = rag_service.preguntar_al_tutor(db, pregunta)
        return respuesta
    except Exception as e:
        print(f"Error en /ask: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ask/stream")
def ask_tutor_stream(pregunta: PreguntaUsuario, db: Session = Depends(get_db)):
    """
    Endpoint de Streaming.
    """
    return StreamingResponse(
        rag_service.preguntar_al_tutor_stream(db, pregunta),
        media_type="text/plain"
    )

@app.post("/knowledge/sync")
def sync_knowledge(db: Session = Depends(get_db)):
    """
    Sincroniza AUTOMÁTICAMENTE el contenido de la tabla 'Temario' a la 'BaseConocimiento'.
    """
    try:
        cantidad = rag_service.sincronizar_temario_a_conocimiento(db)
        return {"mensaje": "Sincronización completada", "registros_nuevos": cantidad}
    except Exception as e:
        print(f"Error al sincronizar conocimiento: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/test")
def test():
    return {"mensaje": "Test exitoso"}

@app.post("/upload/syllabus")
async def upload_syllabus(
    file: UploadFile = File(...), 
    account_id: str = Query(..., description="ID de la cuenta enviado en la URL"), # <--- CAMBIO: Usar Query
    db: Session = Depends(get_db)
):
    """
    Sube el libro entero PDF.
    account_id se puede enviar en la URL (ej: /upload/syllabus?account_id=2)
    """
    if not file.filename.endswith(".pdf"):
         raise HTTPException(status_code=400, detail="Solo se aceptan PDFs por ahora")
         
    try:
        # Llamamos al servicio optimizado (Paralelo)
        resultado = ingest_service.procesar_archivo_temario(db, file, account_id)
        
        # Verificar errores lógicos del servicio
        if isinstance(resultado, dict) and "error" in resultado and resultado["error"]:
             raise HTTPException(status_code=500, detail=resultado["error"])

        return {
            "status": "success", 
            "message": resultado.get("mensaje", "Procesamiento completado"),
            "bloques_procesados": resultado.get("bloques", 0),
            "account_id": account_id
        }
    except Exception as e:
        print(f"Error procesando archivo: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")





@app.post("/ask/audio")
async def ask_audio(request: dict):
    texto_llm = request.get("texto_completo", "")
    # Eliminamos el log inicial de 16 caracteres
    clean_text = texto_llm[16:].strip() if len(texto_llm) > 16 else texto_llm

    # El modelo 'turbo_v2.5' es el más rápido de ElevenLabs (latencia ultrabaja)
    audio_stream = client.text_to_speech.convert_as_stream(
    text=clean_text,
    voice_id="Rfj8YxsU5Gg9QdQE7F9O", # Aquí pones el ID de Javier, por ejemplo
    model_id="eleven_turbo_v2_5", 
    output_format="mp3_44100_128"
)

    return StreamingResponse(audio_stream, media_type="audio/mpeg")

