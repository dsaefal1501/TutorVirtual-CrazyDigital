from pydantic import BaseModel
from typing import List, Optional, Dict, Any



class PreguntaUsuario(BaseModel):
    usuario_id: int
    texto: str
    sesion_id: Optional[int] = None # Si es null, crea nueva sesión

class RespuestaTutor(BaseModel):
    sesion_id: int
    respuesta: str
    fuentes: List[str] = [] # De qué parte del temario sacó la info

class UsuarioCreate(BaseModel):
    nombre: str
    email: str
    password: str
    licencia_id: int

class StudentLogin(BaseModel):
    nombre: str
    token: str

class InstructorLogin(BaseModel):
    username: str
    password: str

class InstructorCreate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    nombre_completo: str = "Instructor"
    max_alumnos: int = 10

class ChangePassword(BaseModel):
    user_id: int
    old_password: str
    new_password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    alumno: Optional['AlumnoResponse'] = None
    instructor: Optional['InstructorResponse'] = None

class ConocimientoCreate(BaseModel):
    temario_id: int
    contenido: str
    metadatos: Dict[str, Any] = {}


# Estructura recursiva para que la IA nos devuelva el árbol de temas
class EstructuraTema(BaseModel):
    title: str
    description: str
    subtopics: List['EstructuraTema'] = []

class AnalisisArchivoResponse(BaseModel):
    mensaje: str
    modulos_creados: int


# --- Schemas para Evaluaciones Dinámicas ---

class AssessmentGenerate(BaseModel):
    """Request para generar una evaluación dinámica."""
    temario_id: int
    num_preguntas: int = 5
    temperatura: float = 0.7

class AssessmentResponse(BaseModel):
    """Response con la evaluación generada."""
    assessment_id: Optional[int] = None
    titulo: str = ""
    total_preguntas: int = 0
    preguntas: List[Dict[str, Any]] = []
    error: Optional[str] = None

class GradeOpenRequest(BaseModel):
    """Request para corregir una respuesta abierta."""
    assessment_id: int
    pregunta_idx: int
    respuesta_alumno: str
    usuario_id: int

class GradeMultipleRequest(BaseModel):
    """Request para corregir respuestas de opción múltiple."""
    assessment_id: int
    respuestas: Dict[int, int]  # {pregunta_idx: indice_respuesta}
    usuario_id: int

class GradeResponse(BaseModel):
    """Response con la calificación."""
    score_id: Optional[int] = None
    score: float = 0.0
    feedback: str = ""
    detalle: Optional[Any] = None
    error: Optional[str] = None

class ContenidoUpdate(BaseModel):
    """Request para actualizar el contenido de un temario manualmente."""
    contenido: str

class AlumnoCreate(BaseModel):
    nombre: str
    licencia_id: int = 1

class AlumnoResponse(BaseModel):
    id: int
    nombre: str
    alias: Optional[str] = None
    token: str
    activo: bool
    must_change_password: bool = True

class InstructorResponse(BaseModel):
    id: int
    nombre: str
    alias: Optional[str] = None
    email: str
    rol: str
    licencia_id: int
    must_change_password: bool = False

class LibroResponse(BaseModel):
    id: int
    titulo: str
    descripcion: Optional[str] = None
    fecha_creacion: Any
    activo: bool

class LibroUpdate(BaseModel):
    titulo: str

class LicenciaResponse(BaseModel):
    id: int
    cliente: str
    max_alumnos: int
    activa: bool

