from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.db.database import get_db, engine
from app.models import modelos
from app.schemas.schemas import (
    PreguntaUsuario, RespuestaTutor, 
    AssessmentGenerate, AssessmentResponse,
    GradeOpenRequest, GradeMultipleRequest, GradeResponse
)
from app.crud import rag_service
from app.crud import ingest_service
from app.crud import assessment_service
from app.crud import tts_service

# Crear las tablas automáticamente
modelos.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Tutor Digital API",
    description="API para interactuar con el Tutor Digital basado en RAG, OpenAI Embeddings y Mistral",
    version="0.2",
)

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
    return {"mensaje": "Bienvenido a la API del Tutor Digital v2.0 — RAG + OpenAI Embeddings"}

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
    account_id: str = Query(..., description="ID de la cuenta enviado en la URL"),
    db: Session = Depends(get_db)
):
    """
    Sube el libro entero PDF. Usa chunking token-based (450 tokens, 70 overlap).
    account_id se puede enviar en la URL (ej: /upload/syllabus?account_id=2)
    """
    if not file.filename.endswith(".pdf"):
         raise HTTPException(status_code=400, detail="Solo se aceptan PDFs por ahora")
         
    try:
        resultado = ingest_service.procesar_archivo_temario(db, file, account_id)
        
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


# ============================================================================
# ENDPOINTS DE EVALUACIONES DINÁMICAS (RAG-based)
# ============================================================================

@app.post("/assessments/generate")
def generate_assessment(req: AssessmentGenerate, db: Session = Depends(get_db)):
    """
    Genera una evaluación dinámica basada en el contenido RAG de un temario.
    Incluye preguntas de opción múltiple, verdadero/falso y abiertas.
    """
    try:
        resultado = assessment_service.generar_evaluacion(
            db=db,
            temario_id=req.temario_id,
            num_preguntas=req.num_preguntas,
            temperatura=req.temperatura,
        )
        if "error" in resultado:
            raise HTTPException(status_code=400, detail=resultado["error"])
        return resultado
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error generando evaluación: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/assessments/grade/open")
def grade_open_answer(req: GradeOpenRequest, db: Session = Depends(get_db)):
    """
    Corrige una respuesta abierta usando LLM-as-a-Judge (corrección semántica).
    """
    try:
        resultado = assessment_service.corregir_respuesta_abierta(
            db=db,
            assessment_id=req.assessment_id,
            pregunta_idx=req.pregunta_idx,
            respuesta_alumno=req.respuesta_alumno,
            usuario_id=req.usuario_id,
        )
        if "error" in resultado:
            raise HTTPException(status_code=400, detail=resultado["error"])
        return resultado
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error corrigiendo respuesta abierta: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/assessments/grade/multiple")
def grade_multiple_choice(req: GradeMultipleRequest, db: Session = Depends(get_db)):
    """
    Corrige respuestas de opción múltiple/verdadero-falso (determinista).
    """
    try:
        resultado = assessment_service.corregir_opcion_multiple(
            db=db,
            assessment_id=req.assessment_id,
            respuestas=req.respuestas,
            usuario_id=req.usuario_id,
        )
        if "error" in resultado:
            raise HTTPException(status_code=400, detail=resultado["error"])
        return resultado
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error corrigiendo opción múltiple: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINT DE TEXT-TO-SPEECH (Azure gpt-4o-mini-tts)
# ============================================================================

@app.post("/tts")
async def text_to_speech(
    texto: str = Form(..., description="Texto a convertir en audio"),
    voz: str = Form("alvaro", description="Voz: alvaro, elvira, jorge, dalia"),
    instrucciones: str = Form(None, description="No usado (compatibilidad)"),
    speed: float = Form(1.0, description="Velocidad de reproducción (0.25 a 3.0)"),
):
    """
    Convierte texto a audio usando edge-tts (Microsoft Neural Voices).
    Gratis, rápido y con voz consistente. Endpoint async para máxima velocidad.
    """
    print(f"[TTS] Recibido: texto='{texto[:50]}...', voz={voz}, speed={speed}")
    
    if not texto or not texto.strip():
        raise HTTPException(status_code=400, detail="El texto no puede estar vacío")
    
    try:
        audio_bytes = await tts_service.generar_audio_tts_async(
            texto=texto,
            voz=voz,
            speed=speed,
        )
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=tts_output.mp3"}
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        print(f"Error en TTS: {e}")
        raise HTTPException(status_code=500, detail=f"Error generando audio: {str(e)}")


