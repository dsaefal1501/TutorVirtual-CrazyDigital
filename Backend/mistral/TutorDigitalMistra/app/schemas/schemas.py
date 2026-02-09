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

class ConocimientoCreate(BaseModel):
    temario_id: int
    contenido: str
    metadatos: Dict[str, Any] = {}