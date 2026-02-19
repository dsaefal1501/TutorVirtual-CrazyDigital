import asyncio
import secrets
import string
import logging
from collections import deque
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.db.database import get_db, engine, SessionLocal
from app.schemas.schemas import (
    PreguntaUsuario, RespuestaTutor, ContenidoUpdate,
    AssessmentGenerate, AssessmentResponse,
    GradeOpenRequest, GradeMultipleRequest, GradeResponse,
    StudentLogin, AlumnoResponse
)
from app.schemas import schemas
from app.models import modelos
from app.crud import rag_service
from app.crud import ingest_service
from app.crud import assessment_service
from app.crud import tts_service
from app.auth import get_current_user

# Crear las tablas automáticamente
modelos.Base.metadata.create_all(bind=engine)

# In-memory buffer para logs de consola (panel de desarrolladores)
LOG_BUFFER = deque(maxlen=2000)

class DequeHandler(logging.Handler):
    def __init__(self, buffer_deque: deque):
        super().__init__()
        self.buffer = buffer_deque

    def emit(self, record):
        try:
            msg = self.format(record)
            ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            self.buffer.append(f"[{ts}] {record.levelname}: {msg}")
        except Exception:
            pass

# Añadir handler al logger root para capturar salidas y exponerlas via endpoint
deque_handler = DequeHandler(LOG_BUFFER)
deque_handler.setLevel(logging.DEBUG)
deque_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(deque_handler)
logging.getLogger().setLevel(logging.INFO)

# Global in-memory storage for upload progress (MVP)
upload_progress = {}

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


def _procesar_archivo_en_thread(content: bytes, filename: str, account_id: str, title: str = None, licencia_id: int = None):
    """
    Wrapper para procesar archivo en un thread separado.
    Recibe los bytes del archivo ya leídos para evitar problemas de I/O en threads.
    """
    # Derive title for frontend matching
    # Must match ingest_service logic: filename.replace(".pdf", "")
    base_title = title if title else filename.replace(".pdf", "")

    def progress_callback(msg, pct):
        print(f"[PROGRESS {account_id}] {pct}% - {msg}")
        upload_progress[account_id] = {
            "status": "processing",
            "message": msg,
            "percent": pct,
            "filename": filename,
            "titulo": base_title
        }

    db = SessionLocal()
    try:
        # Initialize progress
        progress_callback("Iniciando...", 0)
        
        # Pasamos bytes y nombre de archivo al servicio
        result = ingest_service.procesar_archivo_temario(db, content, filename, account_id, progress_callback=progress_callback, titulo=title, licencia_id=licencia_id)
        
        # Final success state
        upload_progress[account_id] = {
            "status": "completed",
            "message": "Proceso completado exitosamente",
            "percent": 100,
            "filename": filename,
            "titulo": base_title
        }
        return result
    except Exception as e:
        upload_progress[account_id] = {
            "status": "error",
            "message": str(e),
            "percent": 0,
            "filename": filename,
            "titulo": base_title
        }
        print(f"Error en thread de proceso: {e}")
    finally:
        db.close()


from fastapi import BackgroundTasks

@app.post("/upload/syllabus")
async def upload_syllabus(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...), 
    account_id: str = Query(..., description="ID de la cuenta enviado en la URL"),
    title: str = Form(None),
    licencia_id: Optional[int] = Query(None)
):
    """
    Sube el libro entero PDF. 
    Procesamiento en SEGUNDO PLANO (Background Task) para evitar timeouts.
    """
    if not file.filename.endswith(".pdf"):
         raise HTTPException(status_code=400, detail="Solo se aceptan PDFs por ahora")
         
    try:
        # LEER CONTENIDO ANTES DE PASAR AL THREAD/BACKGROUND
        content = await file.read()
        filename = file.filename
        
        # Encolar tarea en segundo plano
        background_tasks.add_task(_procesar_archivo_en_thread, content, filename, account_id, title, licencia_id)
        
        return {
            "status": "processing", 
            "message": "Archivo recibido. El procesamiento ha comenzado en segundo plano. Puede tardar unos minutos.",
            "filename": filename,
            "account_id": account_id
        }
    except Exception as e:
        print(f"Error iniciando carga: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")


@app.get("/upload/progress/{account_id}")
def get_upload_progress(account_id: str):
    """
    Devuelve el estado actual del procesamiento de ingestión.
    """
    status = upload_progress.get(account_id, {"status": "idle", "message": "No hay procesos activos", "percent": 0})
    return status


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
    pitch: str = Form("+0Hz", description="Tono (ej: +5Hz, -2Hz)"),
):
    """
    Convierte texto a audio usando edge-tts (Microsoft Neural Voices).
    Gratis, rápido y con voz consistente. Endpoint async para máxima velocidad.
    """
    if not texto or not texto.strip():
        raise HTTPException(status_code=400, detail="El texto no puede estar vacío")
    
    try:
        audio_bytes = await tts_service.generar_audio_tts_async(
            texto=texto,
            voz=voz,
            speed=speed,
            pitch=pitch,
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


# ============================================================================
# ENDPOINTS DE VISUALIZACIÓN DE TEMARIO (INSTRUCTOR)
# ============================================================================

@app.get("/libros", response_model=List[schemas.LibroResponse])
def get_libros(licencia_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """
    Devuelve la lista de libros subidos, opcionalmente filtrada por licencia.
    """
    query = db.query(modelos.Libro)
    if licencia_id:
        query = query.filter(modelos.Libro.licencia_id == licencia_id)
    return query.order_by(modelos.Libro.fecha_creacion.desc()).all()

@app.get("/syllabus")
def get_syllabus(licencia_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """
    Devuelve la jerarquía completa del temario, opcionalmente filtrada por licencia.
    """
    try:
        return rag_service.obtener_jerarquia_temario(db, licencia_id=licencia_id)
    except Exception as e:
        print(f"Error obteniendo syllabus: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/syllabus/{temario_id}/content")
def get_syllabus_content(temario_id: int, recursive: bool = True, db: Session = Depends(get_db)):
    """
    Devuelve el contenido textual de un tema específico.
    """
    try:
        return rag_service.obtener_contenido_tema(db, temario_id, recursivo=recursive)
    except Exception as e:
        print(f"Error obteniendo contenido tema {temario_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/syllabus/{temario_id}/content")
def update_syllabus_content(temario_id: int, req: ContenidoUpdate, db: Session = Depends(get_db)):
    """
    Actualiza el contenido de un tema.
    """
    try:
        return rag_service.actualizar_contenido_tema(db, temario_id, req.contenido)
    except Exception as e:
        print(f"Error actualizando contenido tema {temario_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/libros/{libro_id}")
def update_libro(libro_id: int, req: schemas.LibroUpdate, db: Session = Depends(get_db)):
    """
    Renombra un libro.
    """
    try:
        resultado = rag_service.actualizar_libro(db, libro_id, req.titulo)
        if "error" in resultado:
            raise HTTPException(status_code=404, detail=resultado["error"])
        return resultado
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error actualizando libro {libro_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/syllabus/libro/{libro_id}")
def delete_libro(libro_id: int, db: Session = Depends(get_db)):
    """
    Elimina un libro completo y TODOS sus datos asociados 
    (temarios, base de conocimiento, tests, sesiones, etc.).
    """
    try:
        resultado = rag_service.eliminar_libro_completo(db, libro_id)
        if "error" in resultado:
            raise HTTPException(status_code=404, detail=resultado["error"])
        return resultado
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error eliminando libro {libro_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
@app.get("/licencias/{licencia_id}", response_model=schemas.LicenciaResponse)
def obtener_licencia(licencia_id: int, db: Session = Depends(get_db)):
    licencia = db.query(modelos.Licencia).filter(modelos.Licencia.id == licencia_id).first()
    if not licencia:
        raise HTTPException(status_code=404, detail="Licencia no encontrada")
    return licencia

@app.get("/licencias/{licencia_id}/alumnos", response_model=list[schemas.AlumnoResponse])
def listar_alumnos(licencia_id: int, db: Session = Depends(get_db)):
    # Auto-crear licencia demo si es la 1 y no existe
    if licencia_id == 1:
        licencia = db.query(modelos.Licencia).filter(modelos.Licencia.id == 1).first()
        if not licencia:
            licencia = modelos.Licencia(
                id=1, 
                cliente="Demo School", 
                max_alumnos=5, # Limite demo
                fecha_inicio=datetime.now(),
                fecha_fin=datetime.now(),
                activa=True
            )
            db.add(licencia)
            db.commit()

    # Obtener alumnos
    alumnos = db.query(modelos.Usuario).filter(
        modelos.Usuario.licencia_id == licencia_id,
        modelos.Usuario.rol == 'alumno'
    ).all()
    
    # Mapeamos a respuesta
    resultado = []
    for a in alumnos:
        # En este MVP, usamos password_hash como token visible
        resultado.append(schemas.AlumnoResponse(
            id=a.id,
            nombre=a.nombre,
            alias=a.alias,
            token=a.password_hash, 
            activo=a.activo,
            must_change_password=a.must_change_password
        ))

    return resultado

def _generar_token_unico(longitud=8):
    caracteres = string.ascii_letters + string.digits
    return ''.join(secrets.choice(caracteres) for _ in range(longitud))

def _generar_username_estudiante(alias: str) -> str:
    # 1. Obtener iniciales
    parts = alias.strip().split()
    if not parts:
        initials = "ST" # Student
    else:
        initials = "".join([p[0] for p in parts if p]).upper()
    
    # 2. Generar 5 números aleatorios
    digits = "".join(secrets.choice(string.digits) for _ in range(5))
    
    return f"{initials}{digits}"

@app.post("/licencias/{licencia_id}/alumnos", response_model=schemas.AlumnoResponse)
def crear_alumno(licencia_id: int, alumno_in: schemas.AlumnoCreate, db: Session = Depends(get_db)):
    # Verificar licencia
    licencia = db.query(modelos.Licencia).filter(modelos.Licencia.id == licencia_id).first()
    if not licencia:
        if licencia_id == 1: # Auto-create logic again just in case
             licencia = modelos.Licencia(id=1, cliente="Demo School", max_alumnos=5, fecha_inicio=datetime.now(), fecha_fin=datetime.now(), activa=True)
             db.add(licencia)
             db.commit()
        else:
            raise HTTPException(status_code=404, detail="Licencia no encontrada")
    
    # Verificar límite
    count = db.query(modelos.Usuario).filter(
        modelos.Usuario.licencia_id == licencia_id, 
        modelos.Usuario.rol == 'alumno'
    ).count()
    
    if count >= licencia.max_alumnos:
        raise HTTPException(status_code=400, detail=f"Límite de licencia alcanzado ({licencia.max_alumnos} alumnos máx).")
        
    # Crear alumno
    token = _generar_token_unico()
    
    # Lógica de Alias y Username
    alias_real = alumno_in.nombre
    username_gen = _generar_username_estudiante(alias_real)
    
    # Asegurar unicidad (simple retry logic o confiar en la aleatoriedad con 5 digitos es 1/100000 per initials)
    # Por simplicidad ahora confiamos en la entropía, pero idealmente se verifica DB.
    
    email_dummy = f"{username_gen}@campus.local"
    
    nuevo_alumno = modelos.Usuario(
        nombre=username_gen, # Guardamos el generado (ej: DS59102) como nombre de usuario
        alias=alias_real,    # Guardamos el real (ej: Daniel Saez) como alias
        email=email_dummy,
        password_hash=token, # Token como pass
        rol="alumno",
        licencia_id=licencia_id,
        activo=True
    )
    
    try:
        db.add(nuevo_alumno)
        db.commit()
        db.refresh(nuevo_alumno)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al crear alumno: {str(e)}")
        
    return schemas.AlumnoResponse(
        id=nuevo_alumno.id, 
        nombre=nuevo_alumno.nombre, 
        alias=nuevo_alumno.alias,
        token=nuevo_alumno.password_hash, 
        activo=nuevo_alumno.activo
    )

@app.delete("/licencias/{licencia_id}/alumnos/{alumno_id}")
def delete_alumno(licencia_id: int, alumno_id: int, db: Session = Depends(get_db)):
    # 1. Verificar existencia del alumno y que pertenezca a la licencia
    alumno = db.query(modelos.Usuario).filter(
        modelos.Usuario.id == alumno_id,
        modelos.Usuario.licencia_id == licencia_id,
        modelos.Usuario.rol == 'alumno'
    ).first()
    
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
        
    try:
        # 2. Eliminar dependencias manualmente (Cascade Delete)
        
        # A. Telemetría y Métricas
        db.query(modelos.MetricaConsumo).filter(modelos.MetricaConsumo.usuario_id == alumno_id).delete(synchronize_session=False)
        db.query(modelos.LearningEvent).filter(modelos.LearningEvent.usuario_id == alumno_id).delete(synchronize_session=False)
        
        # B. Progreso Académico y Evaluaciones
        db.query(modelos.IntentoAlumno).filter(modelos.IntentoAlumno.alumno_id == alumno_id).delete(synchronize_session=False)
        db.query(modelos.TestScore).filter(modelos.TestScore.usuario_id == alumno_id).delete(synchronize_session=False)
        db.query(modelos.ProgresoAlumno).filter(modelos.ProgresoAlumno.usuario_id == alumno_id).delete(synchronize_session=False)
        db.query(modelos.Enrollment).filter(modelos.Enrollment.usuario_id == alumno_id).delete(synchronize_session=False)

        # C. Chat (Sesiones, Mensajes, Citas)
        # Obtener IDs de sesiones del alumno
        sesiones = db.query(modelos.SesionChat.id).filter(modelos.SesionChat.alumno_id == alumno_id).all()
        sesion_ids = [s.id for s in sesiones]
        
        if sesion_ids:
            # Borrar Citas de mensajes en estas sesiones
            db.query(modelos.ChatCitas).filter(
                modelos.ChatCitas.mensaje_id.in_(
                    db.query(modelos.MensajeChat.id).filter(modelos.MensajeChat.sesion_id.in_(sesion_ids))
                )
            ).delete(synchronize_session=False)
            
            # Borrar Mensajes de estas sesiones
            db.query(modelos.MensajeChat).filter(modelos.MensajeChat.sesion_id.in_(sesion_ids)).delete(synchronize_session=False)
            
            # Borrar Sesiones
            db.query(modelos.SesionChat).filter(modelos.SesionChat.id.in_(sesion_ids)).delete(synchronize_session=False)
            
        # Limpieza adicional: Mensajes huérfanos con usuario_id (por si acaso)
        db.query(modelos.MensajeChat).filter(modelos.MensajeChat.usuario_id == alumno_id).delete(synchronize_session=False)

        # 3. Eliminar Usuario final
        db.delete(alumno)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error eliminando alumno {alumno_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error al eliminar alumno: {str(e)}")
        
    return {"mensaje": "Alumno eliminado correctamente"}

# ============================================================================
# AUTHENTICATION
# ============================================================================

@app.post("/auth/login/student", response_model=schemas.Token)
def login_student(creds: schemas.StudentLogin, db: Session = Depends(get_db)):
    """
    Valida credenciales de alumno y devuelve un JWT.
    """
    from app.auth import create_access_token # Importar aquí para evitar ciclo si fuera necesario

    # Buscar usuario por nombre
    user = db.query(modelos.Usuario).filter(
        modelos.Usuario.nombre == creds.nombre,
        modelos.Usuario.rol == 'alumno',
        modelos.Usuario.activo == True
    ).first()

    if not user:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    # Verificar credenciales
    is_valid = False
    
    # CASO 1: Primer login (Token plano)
    if user.must_change_password:
        if user.password_hash == creds.token:
            is_valid = True
            
    # CASO 2: Login normal (Contraseña hasheada)
    else:
        try:
            from passlib.context import CryptContext
            # Usar pbkdf2_sha256 que es lo que usamos al cambiar la pass
            pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
            if pwd_context.verify(creds.token, user.password_hash):
                is_valid = True
        except Exception as e:
            print(f"Error verificando hash: {e}")
            pass

    if not is_valid:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    # Generar JWT (subject debe ser string)
    access_token = create_access_token(data={"sub": str(user.id)})

    # Mapear AlumnoResponse
    alumno_data = schemas.AlumnoResponse(
        id=user.id,
        nombre=user.nombre,
        alias=user.alias,
        token=user.password_hash,
        activo=user.activo,
        must_change_password=user.must_change_password
    )

    return schemas.Token(
        access_token=access_token,
        token_type="bearer",
        alumno=alumno_data
    )

@app.post("/auth/login/instructor", response_model=schemas.Token)
def login_instructor(creds: schemas.InstructorLogin, db: Session = Depends(get_db)):
    """
    Valida credenciales de instructor y devuelve un JWT.
    """
    from app.auth import create_access_token 

    # Buscar usuario por nombre (username)
    user = db.query(modelos.Usuario).filter(
        modelos.Usuario.nombre == creds.username,
        modelos.Usuario.rol == 'instructor',
        modelos.Usuario.activo == True
    ).first()

    # Si no existe, comprobamos si es el primer login y creamos uno por defecto solo si no hay instructores
    if not user:
        count = db.query(modelos.Usuario).filter(modelos.Usuario.rol == 'instructor').count()
        # Backdoor para primer inicio: admin/admin crea el instructor
        if count == 0 and creds.username == "admin" and creds.password == "admin":
             # Create default license if not exists
             licencia = db.query(modelos.Licencia).filter(modelos.Licencia.id == 1).first()
             if not licencia:
                 licencia = modelos.Licencia(id=1, cliente="Demo School", max_alumnos=5, fecha_inicio=datetime.now(), fecha_fin=datetime.now(), activa=True)
                 db.add(licencia)
                 db.commit()
             
             # Hash password
             from passlib.context import CryptContext
             pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
             hashed = pwd_context.hash("admin")
             
             user = modelos.Usuario(
                 nombre="admin",
                 alias="Instructor Principal",
                 email="admin@tutor.local",
                 password_hash=hashed,
                 rol="instructor",
                 licencia_id=1,
                 activo=True,
                 must_change_password=False
             )
             db.add(user)
             db.commit()
             db.refresh(user)
        else:
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

    # Verificar password
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
    
    if not pwd_context.verify(creds.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    # Generar JWT
    access_token = create_access_token(data={"sub": str(user.id)})

    # Mapear InstructorResponse
    instructor_data = schemas.InstructorResponse(
        id=user.id,
        nombre=user.nombre,
        email=user.email,
        rol=user.rol,
        licencia_id=user.licencia_id,
        must_change_password=user.must_change_password
    )

    return schemas.Token(
        access_token=access_token,
        token_type="bearer",
        instructor=instructor_data
    )

@app.post("/dev/create-instructor")
def create_instructor(data: schemas.InstructorCreate, db: Session = Depends(get_db)):
    """
    Endpoint para DEVS: Crea un usuario con rol 'instructor'.
    Hashea la contraseña antes de guardarla.
    """
    # 0. Auto-generar credenciales
    import string
    import secrets

    # REGLA: 
    # data.nombre_completo -> ALIAS (Nombre Real, ej: "Juan Pérez")
    # generated_username -> NOMBRE (Login, ej: "JP49201")
    
    alias_real = data.nombre_completo
    
    # Generar username igual que alumnos (Iniciales + 5 dígitos)
    # Reutilizamos la lógica si es accesible o la replicamos
    parts = alias_real.strip().split()
    if not parts:
        initials = "IN" # Instructor
    else:
        initials = "".join([p[0] for p in parts if p]).upper()
    
    digits = "".join(secrets.choice(string.digits) for _ in range(5))
    generated_username = f"{initials}{digits}"

    # Generar Password (Token)
    generated_password = data.password
    if not generated_password:
        caracteres = string.ascii_letters + string.digits
        generated_password = ''.join(secrets.choice(caracteres) for _ in range(8))

    # 1. Verificar si ya existe (el generado)
    # Retry simple
    if db.query(modelos.Usuario).filter(modelos.Usuario.nombre == generated_username).first():
        digits = "".join(secrets.choice(string.digits) for _ in range(5))
        generated_username = f"{initials}{digits}"
        if db.query(modelos.Usuario).filter(modelos.Usuario.nombre == generated_username).first():
             raise HTTPException(status_code=400, detail="Error de colisión de usuario, intente de nuevo")

    # 2. Crear una nueva licencia para este instructor
    nueva_licencia = modelos.Licencia(
         cliente=alias_real, 
         max_alumnos=data.max_alumnos, 
         fecha_inicio=datetime.now(), 
         fecha_fin=datetime.now() + timedelta(days=365), # 1 año
         activa=True
    )
    db.add(nueva_licencia)
    db.commit() # Commit para obtener el ID
    db.refresh(nueva_licencia)

    # 3. Hashear password (Token temporal)
    # El instructor usará este token como password la primera vez
    # En el login, si must_change_password=True, comparamos hash vs token (o plano si así está implementado en login alumno)
    # REVISANDO LOGIN ALUMNO: 
    # - Si must_change_password es True, compara hash == token PLANO (user.password_hash == creds.token)
    # - Por lo tanto, aquí debemos guardar el token PLANO en password_hash inicialmente si queremos seguir esa lógica
    # - PERO: Instructor login suele usar hash.
    # - Vamos a guardar el HASH del token, y en login verificamos HASH vs TOKEN.
    
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
    hashed_password = pwd_context.hash(generated_password)

    # 4. Crear usuario
    nuevo_instructor = modelos.Usuario(
        nombre=generated_username,      # Login (ej: JP84920)
        alias=alias_real,               # Nombre Real (ej: Juan Pérez)
        email=f"{generated_username}@instructor.local", # Dummy email
        password_hash=hashed_password,  # Hash del token
        rol="instructor",
        licencia_id=nueva_licencia.id,
        activo=True,
        must_change_password=True       # Obligar cambio
    )

    try:
        db.add(nuevo_instructor)
        db.commit()
        db.refresh(nuevo_instructor)
        
        return {
            "mensaje": "Instructor creado con éxito",
            "id": nuevo_instructor.id,
            "username": generated_username,  # Esto es lo que usará para entrar
            "password": generated_password   # Token temporal
        }
    except Exception as e:
        db.rollback()
        print(f"Error creando instructor: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dev/logs")
def get_logs(limit: int = 200):
    """
    Dev endpoint: devuelve las últimas líneas capturadas del log en memoria.
    """
    # Devolver las últimas `limit` entradas
    lines = list(LOG_BUFFER)
    if limit and limit > 0:
        return lines[-limit:]
    return lines


@app.get("/dev/logs/stream")
def stream_logs():
    """
    Endpoint SSE (Server-Sent Events) que emite nuevas entradas del log.
    """
    async def event_generator():
        last_index = 0
        while True:
            buffer_list = list(LOG_BUFFER)
            if len(buffer_list) > last_index:
                new = buffer_list[last_index:]
                for ln in new:
                    yield f"data: {ln}\n\n"
                last_index = len(buffer_list)
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/dev/instructors", response_model=List[schemas.InstructorResponse])
def list_instructors(db: Session = Depends(get_db)):
    """
    Endpoint para DEVS: Lista todos los instructores.
    """
    instructors = db.query(modelos.Usuario).filter(modelos.Usuario.rol == 'instructor').all()
    return [
        schemas.InstructorResponse(
            id=i.id,
            nombre=i.nombre,
            alias=i.alias,
            email=i.email,
            rol=i.rol,
            licencia_id=i.licencia_id
        ) for i in instructors
    ]



@app.get("/dev/instructors", response_model=List[schemas.InstructorResponse])
def list_instructors(db: Session = Depends(get_db)):
    """
    Endpoint para DEVS: Lista todos los instructores.
    """
    instructors = db.query(modelos.Usuario).filter(modelos.Usuario.rol == 'instructor').all()
    return [
        schemas.InstructorResponse(
            id=i.id,
            nombre=i.nombre,
            email=i.email,
            rol=i.rol
        ) for i in instructors
    ]

@app.get("/dev/licencias")
def list_licencias(db: Session = Depends(get_db)):
    """
    Endpoint para DEVS: Lista todas las licencias con contador de usuarios.
    """
    licencias = db.query(modelos.Licencia).all()
    results = []
    for lic in licencias:
        user_count = db.query(modelos.Usuario).filter(
            modelos.Usuario.licencia_id == lic.id,
            modelos.Usuario.rol == 'alumno'
        ).count()
        results.append({
            "id": lic.id,
            "cliente": lic.cliente,
            "max_alumnos": lic.max_alumnos,
            "usuarios_actuales": user_count,
            "activa": lic.activa,
            "fecha_fin": lic.fecha_fin.strftime("%Y-%m-%d") if lic.fecha_fin else None
        })
    return results

@app.delete("/dev/instructor/{user_id}")
def delete_instructor(user_id: int, db: Session = Depends(get_db)):
    """
    Endpoint para DEVS: Elimina un instructor por ID.
    Realiza un BORRADO EN CASCADA COMPLETO.
    """
    instructor = db.query(modelos.Usuario).filter(modelos.Usuario.id == user_id, modelos.Usuario.rol == 'instructor').first()
    if not instructor:
        raise HTTPException(status_code=404, detail="Instructor no encontrado")
        
    try:
        # Recuperar la licencia asociada
        licencia_id = instructor.licencia_id
        licencia = db.query(modelos.Licencia).filter(modelos.Licencia.id == licencia_id).first()
        
        should_delete_license = False
        if licencia and licencia.id != 1:
             # Verificar si hay OTROS instructores usando esta misma licencia
             other_instructors = db.query(modelos.Usuario).filter(
                 modelos.Usuario.licencia_id == licencia.id, 
                 modelos.Usuario.id != instructor.id,
                 modelos.Usuario.rol == 'instructor'
             ).count()
             
             # Si no hay otros instructores, asumimos que la licencia era dedicada a este usuario -> BORRAR
             if other_instructors == 0:
                 should_delete_license = True
        
        # ---------------------------------------------------------
        # 1. BORRADO DE ALUMNOS Y SUS DATOS (Cascade Manual)
        # ---------------------------------------------------------
        alumnos = db.query(modelos.Usuario).filter(modelos.Usuario.licencia_id == licencia_id, modelos.Usuario.rol == 'alumno').all()
        
        for alumno in alumnos:
            # Borrar datos relacionados
            db.query(modelos.ProgresoAlumno).filter(modelos.ProgresoAlumno.usuario_id == alumno.id).delete()
            db.query(modelos.IntentoAlumno).filter(modelos.IntentoAlumno.alumno_id == alumno.id).delete()
            db.query(modelos.TestScore).filter(modelos.TestScore.usuario_id == alumno.id).delete()
            db.query(modelos.LearningEvent).filter(modelos.LearningEvent.usuario_id == alumno.id).delete()
            db.query(modelos.MetricaConsumo).filter(modelos.MetricaConsumo.usuario_id == alumno.id).delete()
            
            # Borrar sesiones y mensajes 
            sesiones = db.query(modelos.SesionChat).filter(modelos.SesionChat.alumno_id == alumno.id).all()
            for s in sesiones:
                 db.query(modelos.MensajeChat).filter(modelos.MensajeChat.sesion_id == s.id).delete()
            db.query(modelos.SesionChat).filter(modelos.SesionChat.alumno_id == alumno.id).delete()

            # Borrar Enrollments del alumno
            db.query(modelos.Enrollment).filter(modelos.Enrollment.usuario_id == alumno.id).delete()
            
            # Borrar el alumno
            db.delete(alumno)
        
        # ---------------------------------------------------------
        # 2. BORRADO DE LIBROS ASOCIADOS A ESTA LICENCIA
        # ---------------------------------------------------------
        # Ahora los libros tienen licencia_id directa. Obtenemos todos los de esta licencia.
        libros_licencia = db.query(modelos.Libro).filter(modelos.Libro.licencia_id == licencia_id).all()
        libros_ids = [l.id for l in libros_licencia]
        
        # También buscar libros referenciados vía Enrollment por si acaso hubiera residuos
        enrollments_licencia = db.query(modelos.Enrollment).filter(modelos.Enrollment.licencia_id == licencia_id).all()
        libros_ids_enroll = [e.libro_id for e in enrollments_licencia]
        
        libros_ids_totales = list(set(libros_ids + libros_ids_enroll))
        
        for lid in libros_ids_totales:
            # Si vamos a borrar la licencia (porque no hay otros instructores),
            # borramos el libro sin dudar. Si no, solo si no se usa en otras licencias.
            if should_delete_license:
                rag_service.eliminar_libro_completo(db, lid)
            else:
                # Contar usos en otras licencias
                otros_usos = db.query(modelos.Enrollment).filter(
                    modelos.Enrollment.libro_id == lid, 
                    modelos.Enrollment.licencia_id != licencia_id
                ).count()
                
                # También verificar si el libro pertenece directamente a otra licencia (aunque esto no debería pasar en este modelo)
                if otros_usos == 0:
                    rag_service.eliminar_libro_completo(db, lid)

        # Borrar Enrollments restantes de la licencia
        db.query(modelos.Enrollment).filter(modelos.Enrollment.licencia_id == licencia_id).delete()

        # ---------------------------------------------------------
        # 3. BORRAR INSTRUCTOR Y LICENCIA
        # ---------------------------------------------------------
        db.delete(instructor)
        
        if should_delete_license and licencia:
            db.delete(licencia)

        db.commit()
        return {"mensaje": f"Instructor y datos asociados eliminados. Licencia borrada: {should_delete_license}"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error borrando instructor: {str(e)}")

@app.delete("/dev/licencia/{licencia_id}")
def delete_licencia(licencia_id: int, db: Session = Depends(get_db)):
    """
    Endpoint para DEVS: Elimina una licencia directamente por su ID.
    Realiza un BORRADO EN CASCADA COMPLETO de usuarios y libros.
    """
    licencia = db.query(modelos.Licencia).filter(modelos.Licencia.id == licencia_id).first()
    if not licencia:
        raise HTTPException(status_code=404, detail="Licencia no encontrada")
    
    if licencia_id == 1:
        raise HTTPException(status_code=400, detail="No se puede eliminar la licencia de sistema (ID 1)")

    try:
        print(f"DEBUG: Iniciando borrado directo de Licencia {licencia_id}...")

        # 1. BORRAR USUARIOS
        usuarios = db.query(modelos.Usuario).filter(modelos.Usuario.licencia_id == licencia_id).all()
        for usr in usuarios:
            db.query(modelos.ProgresoAlumno).filter(modelos.ProgresoAlumno.usuario_id == usr.id).delete()
            db.query(modelos.IntentoAlumno).filter(modelos.IntentoAlumno.alumno_id == usr.id).delete()
            db.query(modelos.TestScore).filter(modelos.TestScore.usuario_id == usr.id).delete()
            db.query(modelos.LearningEvent).filter(modelos.LearningEvent.usuario_id == usr.id).delete()
            db.query(modelos.MetricaConsumo).filter(modelos.MetricaConsumo.usuario_id == usr.id).delete()
            
            sesiones = db.query(modelos.SesionChat).filter(modelos.SesionChat.alumno_id == usr.id).all()
            for s in sesiones:
                 db.query(modelos.MensajeChat).filter(modelos.MensajeChat.sesion_id == s.id).delete()
            db.query(modelos.SesionChat).filter(modelos.SesionChat.alumno_id == usr.id).delete()

            db.query(modelos.Enrollment).filter(modelos.Enrollment.usuario_id == usr.id).delete()
            db.delete(usr)
        
        db.commit() # Commit usuarios

        # 2. BORRAR ENROLLMENTS HUÉRFANOS
        db.query(modelos.Enrollment).filter(modelos.Enrollment.licencia_id == licencia_id).delete()
        db.commit()

        # 3. BORRAR LIBROS PROPIOS
        libros_propios = db.query(modelos.Libro).filter(modelos.Libro.licencia_id == licencia_id).all()
        for libro in libros_propios:
            try:
                rag_service.eliminar_libro_completo(db, libro.id)
            except:
                # Fallback manual
                try:
                    db.rollback()
                    db.query(modelos.Temario).filter(modelos.Temario.libro_id == libro.id).delete()
                    db.query(modelos.Enrollment).filter(modelos.Enrollment.libro_id == libro.id).delete()
                    l_del = db.query(modelos.Libro).filter(modelos.Libro.id == libro.id).first()
                    if l_del: db.delete(l_del)
                    db.commit()
                except: pass

        # 4. BORRAR LICENCIA
        # Re-fetch por si acaso
        lic = db.query(modelos.Licencia).filter(modelos.Licencia.id == licencia_id).first()
        if lic:
            db.delete(lic)
            db.commit()
            
        return {"mensaje": f"Licencia {licencia_id} eliminada correctamente."}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
@app.post("/auth/change-password")
def change_password(payload: schemas.ChangePassword, db: Session = Depends(get_db)):
    user = db.query(modelos.Usuario).filter(modelos.Usuario.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
    # Verificar contraseña antigua (en MVP es el token, pero si ya cambió será hash)
    # Si must_change_password es True, asumimos que old_password es el token (texto plano)
    # Si es False, deberíamos verificar hash. 
    # Simplificación: Si el user.password_hash coincide con old_password (texto) o verify(old, hash)
    
    pwd_valid = False
    if user.password_hash == payload.old_password:
        pwd_valid = True
    else:
        # Intentar validar como hash
        try:
            from passlib.context import CryptContext
            pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
            if pwd_context.verify(payload.old_password, user.password_hash):
                pwd_valid = True
        except:
            pass
            
    if not pwd_valid:
        raise HTTPException(status_code=401, detail="Contraseña anterior incorrecta")
        
    # Hashear nueva contraseña
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
    hashed_password = pwd_context.hash(payload.new_password)
    
    user.password_hash = hashed_password
    user.must_change_password = False
    db.commit()
    
    return {"mensaje": "Contraseña actualizada correctamente"}

@app.get("/chat/history", response_model=List[Dict])
def get_chat_history_endpoint(current_user: models.Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Devuelve todo el historial del usuario logueado.
    """
    from app.crud import rag_service
    return rag_service.obtener_historial_usuario(db, current_user.id)
