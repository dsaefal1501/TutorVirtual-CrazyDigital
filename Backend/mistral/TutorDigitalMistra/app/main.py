from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.db.database import get_db, engine
from app.models import modelos
from app.schemas.schemas import PreguntaUsuario, RespuestaTutor, ConocimientoCreate
from app.crud import rag_service
from app.crud import ingest_service
from fastapi import UploadFile, File, Form

# Crear las tablas automáticamente (solo para desarrollo)
# En producción, usa Alembic para migraciones.
modelos.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Tutor Digital API",
    description="API para interactuar con el Tutor Digital basado en RAG y Mistral",
    version="1.0.0"
)

# Configuración de CORS (Permitir que el frontend hable con el backend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, cambia "*" por la URL de tu frontend
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
    1. Recibe la pregunta.
    2. Busca contexto en la DB.
    3. Genera respuesta con Mistral.
    """
    try:
        if not pregunta.texto:
            raise HTTPException(status_code=400, detail="La pregunta no puede estar vacía")
            
        respuesta = rag_service.preguntar_al_tutor(db, pregunta)
        return respuesta
    except Exception as e:
        # Loguear el error real en servidor
        print(f"Error en /ask: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ask/stream")
def ask_tutor_stream(pregunta: PreguntaUsuario, db: Session = Depends(get_db)):
    """
    Endpoint de Streaming. Devuelve texto poco a poco.
    """
    return StreamingResponse(
        rag_service.preguntar_al_tutor_stream(db, pregunta),
        media_type="text/plain"
    )

@app.post("/knowledge/sync")
def sync_knowledge(db: Session = Depends(get_db)):
    """
    Sincroniza AUTOMÁTICAMENTE el contenido de la tabla 'Temario' a la 'BaseConocimiento'.
    Genera embeddings para todos los temas que tengan descripción y no estén ya procesados.
    No requiere parámetros.
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
    file: UploadFile, 
    account_id: str, # UUID de la empresa dueña del temario
    db: Session = Depends(get_db)
):
    """
    Sube un PDF, la IA lo analiza, extrae la estructura y lo guarda 
    vinculado a la cuenta de la empresa especificada.
    """
    if not file.filename.endswith(".pdf"):
         raise HTTPException(status_code=400, detail="Solo se aceptan PDFs por ahora")
         
    try:
        cantidad_temas_raiz = ingest_service.procesar_archivo_temario(db, file, account_id)
        return {
            "status": "success", 
            "message": f"Se procesó el archivo y se crearon {cantidad_temas_raiz} temas principales con sus subtemas.",
            "account_id": account_id
        }
    except Exception as e:
        print(f"Error procesando archivo: {e}")
        raise HTTPException(status_code=500, detail=str(e))