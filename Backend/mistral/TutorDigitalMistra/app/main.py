import asyncio
import secrets
import string
from typing import List, Dict
from datetime import datetime
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


def _procesar_archivo_en_thread(content: bytes, filename: str, account_id: str):
    """
    Wrapper para procesar archivo en un thread separado.
    Recibe los bytes del archivo ya leídos para evitar problemas de I/O en threads.
    """
    # Derive title for frontend matching
    # Must match ingest_service logic: filename.replace(".pdf", "")
    base_title = filename.replace(".pdf", "")

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
        result = ingest_service.procesar_archivo_temario(db, content, filename, account_id, progress_callback=progress_callback)
        
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
        background_tasks.add_task(_procesar_archivo_en_thread, content, filename, account_id)
        
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


# ============================================================================
# ENDPOINTS DE VISUALIZACIÓN DE TEMARIO (INSTRUCTOR)
# ============================================================================

@app.get("/libros", response_model=List[schemas.LibroResponse])
def get_libros(db: Session = Depends(get_db)):
    """
    Devuelve la lista de libros subidos.
    """
    return db.query(modelos.Libro).order_by(modelos.Libro.fecha_creacion.desc()).all()

@app.get("/syllabus")
def get_syllabus(db: Session = Depends(get_db)):
    """
    Devuelve la jerarquía completa del temario (para el árbol del instructor).
    """
    try:
        return rag_service.obtener_jerarquia_temario(db)
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
            activo=a.activo
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
