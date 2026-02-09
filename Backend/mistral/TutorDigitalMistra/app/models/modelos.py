from datetime import datetime
from typing import List, Optional
from sqlalchemy import ForeignKey, String, Integer, Boolean, DateTime, Float, Text, JSON
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

class Temario(Base):
    __tablename__ = "temario"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("temario.id"), nullable=True)
    nombre: Mapped[str] = mapped_column(String(255))
    descripcion: Mapped[Optional[str]] = mapped_column(Text)
    nivel: Mapped[int] = mapped_column(Integer)
    orden: Mapped[int] = mapped_column(Integer)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relación recursiva (Un tema tiene subtemas)
    subtemas: Mapped[List["Temario"]] = relationship("Temario", backref=backref("parent", remote_side=[id]))
    
    # Otras relaciones
    base_conocimiento: Mapped[List["BaseConocimiento"]] = relationship(back_populates="temario")
    preguntas_comunes: Mapped[List["PreguntaComun"]] = relationship(back_populates="temario")
    tests: Mapped[List["Test"]] = relationship(back_populates="temario")
    sesiones: Mapped[List["SesionChat"]] = relationship(back_populates="temario")


class BaseConocimiento(Base):
    __tablename__ = "base_conocimiento"

    id: Mapped[int] = mapped_column(primary_key=True)
    temario_id: Mapped[int] = mapped_column(ForeignKey("temario.id"))
    contenido: Mapped[str] = mapped_column(Text) # El texto original (chunk)
    # Vector de 1024 dimensiones (para Mistral)
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(1024)) 
    metadata_info: Mapped[dict] = mapped_column(JSON, name="metadatos") # Renombrado para evitar conflicto con palabra reservada

    temario: Mapped["Temario"] = relationship(back_populates="base_conocimiento")


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
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(1024))
    info_tecnica: Mapped[Optional[dict]] = mapped_column(JSON) # Tokens usados, modelo, etc.
    fecha: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    sesion: Mapped["SesionChat"] = relationship(back_populates="mensajes")


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
    fecha: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Configuracion(Base):
    __tablename__ = "configuracion"
    
    clave: Mapped[str] = mapped_column(String(100), primary_key=True)
    valor: Mapped[str] = mapped_column(String(255))
    descripcion: Mapped[Optional[str]] = mapped_column(String(255))