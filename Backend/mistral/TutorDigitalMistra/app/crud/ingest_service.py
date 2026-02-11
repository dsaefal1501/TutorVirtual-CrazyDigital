import json
from pydantic import TypeAdapter
from sqlalchemy.orm import Session
from fastapi import UploadFile
from pypdf import PdfReader
from io import BytesIO
from mistralai import Mistral
import os

# Importamos tus modelos (usando la versión actual de modelos.py)
from app.models.modelos import Temario, BaseConocimiento
from app.crud import rag_service

api_key = os.getenv("MISTRAL_API_KEY")
client = Mistral(api_key=api_key) if api_key else None

def extraer_texto_pdf(file: UploadFile) -> str:
    """Lee el archivo PDF en memoria y saca el texto plano."""
    content = file.file.read()
    reader = PdfReader(BytesIO(content))
    texto_completo = ""
    for page in reader.pages:
        texto_completo += page.extract_text() + "\n"
    return texto_completo[:30000] # OJO: Limitamos caracteres para no romper el contexto de la IA

def analizar_estructura_con_ia(texto: str) -> list[dict]:
    """Usa Mistral para convertir texto plano en JSON jerárquico."""
    if not client: raise Exception("No hay API Key de Mistral")

    prompt_arquitecto = """
    ERES UN ARQUITECTO DE DATOS. Analiza el siguiente texto educativo.
    Devuelve ÚNICAMENTE un JSON válido con la siguiente estructura exacta:
    {
        "temas": [
            {"nombre": "...", "descripcion": "...", "nivel": ..., "orden": ...},
            ...
        ]
    }
    
    donde nivel es el nivel de jerarquía y orden es el orden en el que se encuentra.
    Interpretación de Metadatos:
    Cada fragmento de información tiene un parent_id (el tema contenedor) y un orden (su posición relativa).
    En la jerarquía cada nivel se asigna a un tipo de información,
    nivel 1 es el tema 1
    nivel 2 es un punto 1.1 
    nivel 3 es un subpunto 1.1.1

    Ejemplo: Tema 1 es el nivel 1 “el nivel mas alto”, y el orden 1 y el siguiente tema es el nivel 1 y el orden 2.
    Si el siguiente tema es el punto 1.1 es el nivel 2 y el orden 1.
    Si el siguiente tema es el subpunto 1.1.1 es el nivel 3 y el orden 1.
    Si el siguiente tema es el punto 1.2 es el nivel 2 y el orden 2.
    Si el siguiente tema es el subpunto 1.2.1 es el nivel 3 y el orden 1.


    Detecta la jerarquía por los títulos. Resume el contenido en 'descripcion'.
    """

    chat_response = client.chat.complete(
        model="mistral-large-latest", # Usar modelo inteligente para esto
        messages=[
            {"role": "system", "content": prompt_arquitecto},
            {"role": "user", "content": f"TEXTO A ANALIZAR:\n{texto}"}
        ],
        response_format={"type": "json_object"} # Forzar JSON mode (Vital)
    )
    
    # Parsear respuesta
    raw_json = chat_response.choices[0].message.content
    print(f"DEBUG - Raw JSON from AI: {raw_json}") # Para depuración
    
    try:
        data = json.loads(raw_json)
        
        # 1. Caso ideal: Tiene la clave "temas"
        if isinstance(data, dict) and "temas" in data and isinstance(data["temas"], list):
            return data["temas"]
            
        # 2. Caso legacy: Tiene la clave "topics"
        if isinstance(data, dict) and "topics" in data and isinstance(data["topics"], list):
            return data["topics"]
            
        # 3. Caso directo: Es una lista
        if isinstance(data, list):
            return data
            
        # 4. Fallback: Buscar cualquier valor que sea una lista en el diccionario
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, list):
                    return value
                    
        # Si llegamos aquí, no se encontró una lista válida
        print("Error: El JSON no contiene una lista de temas válida.")
        return []
    except Exception as e:
        print(f"Error parseando JSON: {e}")
        return []

def _insertar_tema(db: Session, nodo: dict, account_id: str, parent_id=None):
    """
    Función para guardar un tema individual.
    Recibe el nodo con la estructura plana: {"id": "...", "parent_id": "...", "nombre": "...", "descripcion": "...", "nivel": ..., "orden": ...}
    """
    # 1. Crear el Temario (La estructura/índice)
    # Nota: account_id se ignora porque el modelo actual no lo soporta directamente
    nuevo_modulo = Temario(
        parent_id=parent_id,
        nombre=nodo.get('nombre', 'Sin título'),
        descripcion=nodo.get('descripcion', ''),
        nivel=nodo.get('nivel', 1),
        orden=nodo.get('orden', 1)
    )
    db.add(nuevo_modulo)
    db.commit()
    db.refresh(nuevo_modulo)

    # 2. Guardamos la descripción en el Temario.
    # La generación de embeddings y la inserción en BaseConocimiento
    # se realizarán en bloque mediante
    # rag_service.sincronizar_temario_a_conocimiento(db)
    descripcion = nodo.get('descripcion', '')
    if descripcion:
        texto_vectorizar = f"Tema: {nuevo_modulo.nombre}. Nivel: {nuevo_modulo.nivel}. Contenido: {descripcion}"
    
    # Commit final del bloque
    db.commit()
    return nuevo_modulo.id

def procesar_archivo_temario(db: Session, file: UploadFile, account_id: str):
    # 1. Extraer
    texto = extraer_texto_pdf(file)
    
    # 2. Estructurar (IA)
    estructura_json = analizar_estructura_con_ia(texto)
    
    # 3. Guardar en DB (Iterativo con rastreo de padres por nivel)
    # Estructura esperada: [{"nombre": "...", "descripcion": "...", "nivel": 1, "orden": 1}, ...]
    
    count = 0
    last_ids = {} # Diccionario para guardar el ID del último tema de cada nivel: {1: id_tema1, 2: id_tema1_1, ...}

    for nodo in estructura_json:
        nivel = nodo.get('nivel', 1)
        
        # Determinar el parent_id
        parent_id = None
        if nivel > 1:
            # El padre es el último tema visto del nivel inmediatamente superior
            parent_id = last_ids.get(nivel - 1)
        
        # Insertar el tema
        nuevo_id = _insertar_tema(db, nodo, account_id, parent_id=parent_id)
        
        # Actualizar el rastreo de IDs
        last_ids[nivel] = nuevo_id
        
        count += 1
        
    # Después de crear todos los registros de Temario, generamos los
    # embeddings y los guardamos en BaseConocimiento usando la función
    # centralizada de `rag_service` para evitar duplicación de lógica
    try:
        nuevos_kb = rag_service.sincronizar_temario_a_conocimiento(db)
        print(f"Sincronización completada: {nuevos_kb} nuevos registros en BaseConocimiento")
    except Exception as e:
        print(f"Error al sincronizar temario a conocimiento: {e}")

    return count