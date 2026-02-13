from datetime import datetime
from typing import List, Optional
from sqlalchemy import ForeignKey, String, Integer, Boolean, DateTime, Float, Text, JSON, Enum as SQLEnum, Numeric
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, backref
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector  # Necesitas instalar pgvector

# Clase base
class Base(DeclarativeBase):
    pass

# --- Módulo: Usuarios y Licencias ---

class Licencia(Base):
    __tablename__ = "licencias"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente: Mapped[str] = mapped_column(String(255))
    max_alumnos: Mapped[int] = mapped_column(Integer)
    fecha_inicio: Mapped[datetime] = mapped_column(DateTime)
    fecha_fin: Mapped[datetime] = mapped_column(DateTime)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relación 1:N con Usuarios
    usuarios: Mapped[List["Usuario"]] = relationship(back_populates="licencia")
    # Relación 1:N con Enrollments
    enrollments: Mapped[List["Enrollment"]] = relationship(back_populates="licencia")


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    licencia_id: Mapped[int] = mapped_column(ForeignKey("licencias.id"))
    nombre: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    rol: Mapped[str] = mapped_column(String(50)) # 'alumno', 'admin', etc.
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relaciones
    licencia: Mapped["Licencia"] = relationship(back_populates="usuarios")
    intentos: Mapped[List["IntentoAlumno"]] = relationship(back_populates="alumno")
    sesiones_chat: Mapped[List["SesionChat"]] = relationship(back_populates="alumno")
    metricas: Mapped[List["MetricaConsumo"]] = relationship(back_populates="usuario")


# --- Módulo: Contenidos (Temario y RAG) ---

class Libro(Base):
    __tablename__ = "libros"

    id: Mapped[int] = mapped_column(primary_key=True)
    titulo: Mapped[str] = mapped_column(String(255))
    autor: Mapped[Optional[str]] = mapped_column(String(255))
    descripcion: Mapped[Optional[str]] = mapped_column(Text)
    pdf_path: Mapped[Optional[str]] = mapped_column(String(500))
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relaciones
    temarios: Mapped[List["Temario"]] = relationship(back_populates="libro")
    enrollments: Mapped[List["Enrollment"]] = relationship(back_populates="libro")


class Temario(Base):
    __tablename__ = "temario"

    id: Mapped[int] = mapped_column(primary_key=True)
    libro_id: Mapped[Optional[int]] = mapped_column(ForeignKey("libros.id"), nullable=True)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("temario.id"), nullable=True)
    nombre: Mapped[str] = mapped_column(String(255))
    descripcion: Mapped[Optional[str]] = mapped_column(Text)
    nivel: Mapped[int] = mapped_column(Integer)
    orden: Mapped[int] = mapped_column(Integer)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # --- NUEVO CAMPO ---
    pagina_inicio: Mapped[Optional[int]] = mapped_column(Integer, nullable=True) 

    # Relaciones existentes
    libro: Mapped[Optional["Libro"]] = relationship(back_populates="temarios")
    subtemas: Mapped[List["Temario"]] = relationship("Temario", backref=backref("parent", remote_side=[id]))
    base_conocimiento: Mapped[List["BaseConocimiento"]] = relationship(back_populates="temario")
    preguntas_comunes: Mapped[List["PreguntaComun"]] = relationship(back_populates="temario")
    tests: Mapped[List["Test"]] = relationship(back_populates="temario")
    sesiones: Mapped[List["SesionChat"]] = relationship(back_populates="temario")
    # Nueva relación con progreso
    progreso: Mapped[List["ProgresoAlumno"]] = relationship(back_populates="temario")

class BaseConocimiento(Base):
    __tablename__ = "base_conocimiento"

    id: Mapped[int] = mapped_column(primary_key=True)
    temario_id: Mapped[int] = mapped_column(ForeignKey("temario.id"))
    contenido: Mapped[str] = mapped_column(Text) # El texto original
    
    # --- NUEVOS CAMPOS PARA ENSEÑANZA SECUENCIAL ---
    tipo_contenido: Mapped[str] = mapped_column(String(50), default='texto') # 'texto', 'codigo', etc.
    orden_aparicion: Mapped[int] = mapped_column(Integer, default=0)
    ref_fuente: Mapped[Optional[str]] = mapped_column(String(100))
    pagina: Mapped[Optional[int]] = mapped_column(Integer)

    # Lista enlazada para navegación secuencial
    chunk_anterior_id: Mapped[Optional[int]] = mapped_column(ForeignKey("base_conocimiento.id"), nullable=True)
    chunk_siguiente_id: Mapped[Optional[int]] = mapped_column(ForeignKey("base_conocimiento.id"), nullable=True)

    # Vector RAG + Full-Text Search
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(1536))  # OpenAI text-embedding-3-small
    # busqueda_texto es TSVECTOR (gestionado por trigger SQL, no se mapea en Python)
    metadata_info: Mapped[dict] = mapped_column(JSON, name="metadatos")

    temario: Mapped["Temario"] = relationship(back_populates="base_conocimiento")
    # Relación inversa para saber si este contenido es el último visto por alguien
    progreso_vinculado: Mapped[List["ProgresoAlumno"]] = relationship(back_populates="ultimo_contenido_visto")
    ejercicio: Mapped[Optional["EjercicioCodigo"]] = relationship(back_populates="contenido_base", uselist=False)
    # Relación con citas de chat
    citas: Mapped[List["ChatCitas"]] = relationship(back_populates="base_conocimiento")


class PreguntaComun(Base):
    __tablename__ = "preguntas_comunes"

    id: Mapped[int] = mapped_column(primary_key=True)
    temario_id: Mapped[int] = mapped_column(ForeignKey("temario.id"))
    pregunta: Mapped[str] = mapped_column(Text)
    respuesta: Mapped[str] = mapped_column(Text)

    temario: Mapped["Temario"] = relationship(back_populates="preguntas_comunes")


# --- Módulo: Evaluación (Tests) ---

class Test(Base):
    __tablename__ = "tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    temario_id: Mapped[int] = mapped_column(ForeignKey("temario.id"))
    titulo: Mapped[str] = mapped_column(String(255))
    contenido_examen: Mapped[dict] = mapped_column(JSON) # Preguntas y opciones
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    temario: Mapped["Temario"] = relationship(back_populates="tests")
    intentos: Mapped[List["IntentoAlumno"]] = relationship(back_populates="test")


class IntentoAlumno(Base):
    __tablename__ = "intentos_alumno"

    id: Mapped[int] = mapped_column(primary_key=True)
    alumno_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id"))
    nota_final: Mapped[float] = mapped_column(Float)
    respuestas_alumno: Mapped[dict] = mapped_column(JSON)
    fecha_realizacion: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    alumno: Mapped["Usuario"] = relationship(back_populates="intentos")
    test: Mapped["Test"] = relationship(back_populates="intentos")


# --- Módulo: Chat (Tutor Virtual) ---

class SesionChat(Base):
    __tablename__ = "sesiones_chat"

    id: Mapped[int] = mapped_column(primary_key=True)
    alumno_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    temario_id: Mapped[Optional[int]] = mapped_column(ForeignKey("temario.id")) # Contexto de la sesión
    titulo_resumen: Mapped[str] = mapped_column(String(255))
    fecha_inicio: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    alumno: Mapped["Usuario"] = relationship(back_populates="sesiones_chat")
    temario: Mapped["Temario"] = relationship(back_populates="sesiones")
    mensajes: Mapped[List["MensajeChat"]] = relationship(back_populates="sesion")


class MensajeChat(Base):
    __tablename__ = "mensajes_chat"

    id: Mapped[int] = mapped_column(primary_key=True)
    sesion_id: Mapped[int] = mapped_column(ForeignKey("sesiones_chat.id"))
    rol: Mapped[str] = mapped_column(String(20)) # 'user', 'assistant', 'system'
    texto: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(1536))  # OpenAI text-embedding-3-small
    info_tecnica: Mapped[Optional[dict]] = mapped_column(JSON) # Tokens usados, modelo, etc.
    fecha: Mapped[datetime] = mapped_column(DateTime, server_default=func.now()) # Fecha en la que se envio el mensaje

    sesion: Mapped["SesionChat"] = relationship(back_populates="mensajes")
    # Relación con citas  
    citas: Mapped[List["ChatCitas"]] = relationship(back_populates="mensaje")


class ChatCitas(Base):
    """Tabla para rastrear qué chunks de base_conocimiento se usaron para responder un mensaje."""
    __tablename__ = "chat_citas"

    id: Mapped[int] = mapped_column(primary_key=True)
    mensaje_id: Mapped[int] = mapped_column(ForeignKey("mensajes_chat.id"))
    base_conocimiento_id: Mapped[int] = mapped_column(ForeignKey("base_conocimiento.id"))
    score_similitud: Mapped[Optional[float]] = mapped_column(Float)

    mensaje: Mapped["MensajeChat"] = relationship(back_populates="citas")
    base_conocimiento: Mapped["BaseConocimiento"] = relationship(back_populates="citas")


class EmbeddingCache(Base):
    __tablename__ = "embedding_cache"

    text_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    original_text: Mapped[str] = mapped_column(Text)
    
    # OpenAI text-embedding-3-small = 1536 dimensiones
    embedding: Mapped[list] = mapped_column(Vector(1536))
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
# --- Módulo: Sistema (Logs y Config) ---

class MetricaConsumo(Base):
    __tablename__ = "metricas_consumo"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    servicio: Mapped[str] = mapped_column(String(100)) # ej: "GPT-4", "Embedding"
    tokens_gastados: Mapped[int] = mapped_column(Integer)
    coste: Mapped[float] = mapped_column(Float)
    fecha: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    usuario: Mapped["Usuario"] = relationship(back_populates="metricas")

class LogError(Base):
    __tablename__ = "logs_errores"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    origen: Mapped[str] = mapped_column(String(255))
    nivel: Mapped[str] = mapped_column(String(50)) # ERROR, WARNING, CRITICAL
    mensaje: Mapped[str] = mapped_column(Text)
    fecha: Mapped[datetime] = mapped_column(DateTime, server_default=func.now()) # Fecha cuando ocurrio el error

class Configuracion(Base):
    __tablename__ = "configuracion"
    
    clave: Mapped[str] = mapped_column(String(100), primary_key=True)
    valor: Mapped[str] = mapped_column(String(255))
    descripcion: Mapped[Optional[str]] = mapped_column(String(255))



    # --- Módulo: Progreso Académico ---

class ProgresoAlumno(Base):
    __tablename__ = "progreso_alumno"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    temario_id: Mapped[int] = mapped_column(ForeignKey("temario.id"))
    
    # Referencia al ID específico de la tabla base_conocimiento (el párrafo exacto)
    ultimo_contenido_visto_id: Mapped[Optional[int]] = mapped_column(ForeignKey("base_conocimiento.id"), nullable=True)
    
    estado: Mapped[str] = mapped_column(String(20), default='en_progreso') # 'en_progreso', 'completado'
    
    # Campos para maestría socrática
    nivel_comprension: Mapped[int] = mapped_column(Integer, default=0)  # 0-5
    conceptos_debiles: Mapped[dict] = mapped_column(JSON, default=lambda: [])
    
    fecha_actualizacion: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relaciones para navegar desde el objeto
    usuario: Mapped["Usuario"] = relationship(backref="progresos")
    temario: Mapped["Temario"] = relationship()
    
    # Esta relación permite acceder al texto/código del último punto visto:
    # Ej: progreso.ultimo_contenido_visto.contenido -> "El código print() sirve para..."
    ultimo_contenido_visto: Mapped[Optional["BaseConocimiento"]] = relationship()

    # ... (Clase ProgresoAlumno y otras clases) ...

class EjercicioCodigo(Base):
    __tablename__ = "ejercicios_codigo"

    id: Mapped[int] = mapped_column(primary_key=True)
    base_conocimiento_id: Mapped[int] = mapped_column(ForeignKey("base_conocimiento.id"))
    
    solucion_esperada: Mapped[str] = mapped_column(Text)
    pistas: Mapped[Optional[str]] = mapped_column(Text)
    dificultad: Mapped[int] = mapped_column(Integer, default=1)

    # Aquí NO hay error porque BaseConocimiento ya existe (estaba arriba)
    contenido_base: Mapped["BaseConocimiento"] = relationship("BaseConocimiento", back_populates="ejercicio")


# --- Módulo: LMS Extendido (Matrículas, Evaluaciones IA, Telemetría) ---

class Enrollment(Base):
    """Relación M:N entre Usuarios y Temario (Matrículas)."""
    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    libro_id: Mapped[int] = mapped_column(ForeignKey("libros.id"))  # Cambiado de temario_id
    licencia_id: Mapped[Optional[int]] = mapped_column(ForeignKey("licencias.id"), nullable=True)
    fecha_matricula: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    estado: Mapped[str] = mapped_column(String(20), default='activo')  # activo, suspendido, completado
    progreso_global: Mapped[float] = mapped_column(Float, default=0.0)    # Relaciones
    usuario: Mapped["Usuario"] = relationship(backref="enrollments")
    libro: Mapped["Libro"] = relationship(back_populates="enrollments")  # Cambiado de temario
    licencia: Mapped[Optional["Licencia"]] = relationship(back_populates="enrollments")


class Assessment(Base):
    """Evaluaciones generadas dinámicamente por el pipeline RAG."""
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    temario_id: Mapped[int] = mapped_column(ForeignKey("temario.id"))
    titulo: Mapped[str] = mapped_column(String(255))
    topic_metadata: Mapped[Optional[str]] = mapped_column(String(255))
    total_preguntas: Mapped[int] = mapped_column(Integer, default=0)
    generated_json_payload: Mapped[dict] = mapped_column(JSON)  # Preguntas en formato JSON
    temperatura: Mapped[float] = mapped_column(Float, default=0.7)  # Temperatura usada en generación
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    temario: Mapped["Temario"] = relationship(backref="assessments")
    scores: Mapped[List["TestScore"]] = relationship(back_populates="assessment")


class TestScore(Base):
    """Calificaciones históricas con feedback generado por LLM-as-a-Judge."""
    __tablename__ = "test_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    score: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0 a 100.0
    respuestas_alumno: Mapped[Optional[dict]] = mapped_column(JSON)  # Respuestas en JSON
    ai_feedback_log: Mapped[Optional[str]] = mapped_column(Text)  # Retroalimentación del LLM
    tiempo_segundos: Mapped[Optional[int]] = mapped_column(Integer)  # Tiempo tomado
    fecha_envio: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    assessment: Mapped["Assessment"] = relationship(back_populates="scores")
    usuario: Mapped["Usuario"] = relationship(backref="test_scores")


class LearningEvent(Base):
    """Telemetría de eventos conductuales del alumno en la plataforma."""
    __tablename__ = "learning_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    action_type: Mapped[str] = mapped_column(String(100))  # 'capitulo_visto', 'chat_iniciado', 'test_completado'
    detalle: Mapped[Optional[str]] = mapped_column(Text)  # Info adicional del evento
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    usuario: Mapped["Usuario"] = relationship(backref="learning_events")