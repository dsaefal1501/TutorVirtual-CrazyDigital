"""
Servicio de Ingesta de Documentos — Versión con Chunking Token-Based
Usa fragmentación de tamaño fijo (450 tokens, 70 overlap) en vez de IA para clasificar bloques.
La IA solo se usa para analizar el índice/estructura del libro.
"""
import json
import concurrent.futures
import os
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from fastapi import UploadFile
from pypdf import PdfReader
from io import BytesIO
from mistralai import Mistral

# Importamos modelos y servicios
from app.models.modelos import Temario, BaseConocimiento
from app.crud.embedding_service import generar_embedding, generar_embeddings_batch
from app.crud.chunking_service import procesar_texto_tema

api_key = os.getenv("MISTRAL_API_KEY")
client = Mistral(api_key=api_key) if api_key else None

# ============================================================================
# 1. UTILIDADES DE EXTRACCIÓN PDF
# ============================================================================

def extraer_info_paginada(file: UploadFile) -> List[Dict[str, Any]]:
    """Lee el PDF y devuelve una lista de páginas limpia."""
    file.file.seek(0)
    content = file.file.read()
    reader = PdfReader(BytesIO(content))
    paginas = []
    
    # Textos basura (Cabeceras que se repiten y ensucian)
    basura = ["Python para todos", "Raúl González Duque", "--- PAGE"]
    
    for i, page in enumerate(reader.pages):
        texto = page.extract_text()
        if texto:
            lines = [l for l in texto.split('\n') if not any(b in l for b in basura)]
            paginas.append({
                "numero": i + 1,
                "text": "\n".join(lines)
            })
    return paginas

def obtener_texto_rango(paginas: List[Dict], inicio: int, fin: int) -> str:
    """Extrae texto de un rango de páginas."""
    texto_acumulado = ""
    limite_real = len(paginas) + 1 if fin <= 0 else fin

    for p in paginas:
        if inicio <= p["numero"] < limite_real: 
            texto_acumulado += p["text"] + "\n\n"
            
    # Caso borde: tema de una sola página
    if not texto_acumulado and inicio < len(paginas) + 1:
         for p in paginas:
            if p["numero"] == inicio:
                texto_acumulado += p["text"]
    return texto_acumulado

# ============================================================================
# 2. FASE 1: ARQUITECTO (Estructura Jerárquica — usa IA solo para el índice)
# ============================================================================

def generar_estructura_temario(texto_indice: str) -> List[Dict]:
    if not client: return []
    
    print(f"--- Analizando índice ({len(texto_indice)} caracteres)... ---")

    prompt = """
    ERES UN ANALISTA DE LIBROS. Tu objetivo es convertir el ÍNDICE (Tabla de Contenidos) en una estructura JSON.
    
    ESTRUCTURA DEL LIBRO "PYTHON PARA TODOS":
    1. Los títulos en MAYÚSCULAS o principales son NIVEL 1 (Ej: "INTRODUCCIÓN", "TIPOS BÁSICOS", "COLECCIONES").
    2. Los subtítulos debajo de ellos son NIVEL 2 (Ej: Dentro de "Colecciones" está "Listas", "Tuplas", "Diccionarios").
    
    REGLAS IMPORTANTES:
    - 'pagina_inicio': Busca el número de página en el texto.
    - 'nivel': 1 para Capítulos, 2 para Secciones.
    - 'orden_lectura': Un número global que indica el orden de aparición en el índice (1, 2, 3, 4...).
      Este campo SOLO se usa para mantener el orden de lectura, NO es el orden jerárquico.
    
    FORMATO JSON ESPERADO:
    {
        "temas": [
            {"nombre": "Introducción", "nivel": 1, "orden_lectura": 1, "pagina_inicio": 7},
            {"nombre": "¿Qué es Python?", "nivel": 2, "orden_lectura": 2, "pagina_inicio": 7},
            {"nombre": "Instalación", "nivel": 2, "orden_lectura": 3, "pagina_inicio": 9},
            {"nombre": "Tipos básicos", "nivel": 1, "orden_lectura": 4, "pagina_inicio": 15},
            {"nombre": "Números", "nivel": 2, "orden_lectura": 5, "pagina_inicio": 16}
        ]
    }
    """
    
    try:
        response = client.chat.complete(
            model="mistral-large-latest",
            messages=[
                {"role": "system", "content": prompt}, 
                {"role": "user", "content": f"ÍNDICE A PROCESAR:\n{texto_indice}"}
            ],
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content)
        temas = data.get("temas", [])
        
        temas.sort(key=lambda x: x.get("orden_lectura", x.get("orden", 0)))
        
        print(f"--- Estructura detectada: {len(temas)} temas ---")
        return temas
    except Exception as e:
        print(f"Error generando estructura: {e}")
        return []

def _guardar_temario_recursivo(db: Session, temas: List[Dict]) -> List[Dict]:
    """Guarda en DB con ORDEN RELATIVO al padre."""
    lista_plana_db = []
    padres = {}
    orden_por_padre = {}

    for t in temas:
        nivel_actual = t.get("nivel", 1)
        
        parent_id = padres.get(nivel_actual - 1, {}).get("id") if nivel_actual > 1 else None
        parent_nombre = padres.get(nivel_actual - 1, {}).get("nombre", "") if nivel_actual > 1 else ""
        
        if parent_id not in orden_por_padre:
            orden_por_padre[parent_id] = 0
        orden_por_padre[parent_id] += 1
        orden_relativo = orden_por_padre[parent_id]
        
        indent = "  " * (nivel_actual - 1)
        parent_str = f"(Hijo de '{parent_nombre}' id={parent_id})" if parent_id else "(RAIZ)"
        print(f"{indent}Guardando: {t['nombre']} - Nivel {nivel_actual}, Orden {orden_relativo} {parent_str} - Pag {t.get('pagina_inicio')}")

        nuevo_tema = Temario(
            nombre=t["nombre"],
            nivel=nivel_actual,
            orden=orden_relativo,
            parent_id=parent_id, 
            pagina_inicio=t.get("pagina_inicio", 0),
            descripcion=f"Tema de nivel {nivel_actual} importado",
            activo=True
        )
        db.add(nuevo_tema)
        db.commit()
        db.refresh(nuevo_tema)
        
        padres[nivel_actual] = {"id": nuevo_tema.id, "nombre": t["nombre"]}
        
        if nivel_actual + 1 in padres:
            del padres[nivel_actual + 1]

        t_con_id = t.copy()
        t_con_id["db_id"] = nuevo_tema.id
        t_con_id["parent_id"] = parent_id
        t_con_id["parent_nombre"] = parent_nombre
        t_con_id["orden"] = orden_relativo
        lista_plana_db.append(t_con_id)
        
    return lista_plana_db

# ============================================================================
# 3. FASE 2: CHUNKING TOKEN-BASED (Reemplaza la clasificación por IA)
# ============================================================================

def tarea_procesar_tema(tema_info: Dict, texto_completo: str) -> Dict:
    """
    Worker que fragmenta el contenido usando chunking token-based.
    Ya NO usa la IA para clasificar texto/código — usa heurísticas locales.
    """
    bloques = procesar_texto_tema(
        texto=texto_completo,
        nombre_tema=tema_info["nombre"],
        nivel=tema_info["nivel"],
        orden=tema_info["orden"],
        pagina_inicio=tema_info.get("pagina_inicio", 0),
        parent_nombre=tema_info.get("parent_nombre", ""),
    )
    
    return {
        "tema_id": tema_info["db_id"],
        "nombre": tema_info["nombre"],
        "nivel": tema_info["nivel"],
        "orden": tema_info["orden"],
        "parent_id": tema_info.get("parent_id"),
        "parent_nombre": tema_info.get("parent_nombre", ""),
        "pag_inicio": tema_info.get("pagina_inicio", 0),
        "bloques": bloques,
        "error": None
    }

# ============================================================================
# 4. ORQUESTADOR PRINCIPAL
# ============================================================================

def procesar_archivo_temario(db: Session, file: UploadFile, account_id: str):
    print("=== INICIO DE INGESTA (Chunking Token-Based) ===")
    
    # 1. Leer PDF
    paginas_pdf = extraer_info_paginada(file)
    print(f" -> PDF leído: {len(paginas_pdf)} páginas detectadas.")
    
    # 2. Analizar Índice (IA solo para estructura)
    texto_indice = obtener_texto_rango(paginas_pdf, 4, 7) 
    
    # 3. Generar Estructura (IA)
    temas_raw = generar_estructura_temario(texto_indice)
    
    if not temas_raw:
        return {"error": "La IA no pudo detectar el índice."}

    # 4. Guardar Estructura en DB
    print(" -> Guardando jerarquía en base de datos...")
    temas_db = _guardar_temario_recursivo(db, temas_raw)
    
    # 5. Chunking Token-Based (Paralelo)
    print(f" -> Fragmentando contenido de {len(temas_db)} temas (Token-Based, 450 tokens, 70 overlap)...")
    
    temas_db.sort(key=lambda x: x.get("pagina_inicio", 0))
    tareas = []
    
    for i, tema in enumerate(temas_db):
        p_inicio = tema.get("pagina_inicio", 1)
        
        if i < len(temas_db) - 1:
            p_fin = temas_db[i+1].get("pagina_inicio", p_inicio)
        else:
            p_fin = len(paginas_pdf) + 1
            
        if p_fin <= p_inicio: p_fin = p_inicio + 1
            
        texto = obtener_texto_rango(paginas_pdf, p_inicio, p_fin)
        tareas.append((tema, texto))

    # Ejecutar chunking en paralelo
    resultados = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(tarea_procesar_tema, t, txt): t["db_id"] for t, txt in tareas}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if not res["error"]:
                resultados.append(res)
                print(f"   [OK] {res['nombre']} ({len(res['bloques'])} fragmentos)")

    # 6. Guardar Bloques y Generar Embeddings en BATCH (OpenAI)
    print(" -> Insertando fragmentos y generando embeddings en BATCH (OpenAI text-embedding-3-small)...")
    count_bloques = 0
    resultados.sort(key=lambda x: x["pag_inicio"])
    
    # Preparar todos los textos para embedding en batch
    todos_bloques = []  # Lista de (resultado, bloque, posicion, txt_vector)
    
    for res in resultados:
        if res.get("parent_nombre"):
            posicion = f"{res['parent_nombre']} > {res['nombre']} (nivel {res['nivel']}, orden {res['orden']})"
        else:
            posicion = f"{res['nombre']} (nivel {res['nivel']}, orden {res['orden']})"
        
        for bloque in res["bloques"]:
            txt_vector = f"[{posicion}]: {bloque['contenido']}"
            todos_bloques.append((res, bloque, posicion, txt_vector))
    
    total_fragmentos = len(todos_bloques)
    print(f"   Total fragmentos a indexar: {total_fragmentos}")
    
    # Generar TODOS los embeddings en batch
    textos_para_embedding = [item[3] for item in todos_bloques]
    vectores = generar_embeddings_batch(db, textos_para_embedding)
    
    # Insertar en base_conocimiento con los vectores ya generados
    for i, (res, bloque, posicion, txt_vector) in enumerate(todos_bloques):
        meta = {
            **bloque["metadata"],
            "parent_id": res.get("parent_id"),
        }
        
        nuevo_bk = BaseConocimiento(
            temario_id=res["tema_id"],
            contenido=bloque["contenido"],
            tipo_contenido=bloque["tipo"],
            orden_aparicion=bloque["orden"],
            pagina=res["pag_inicio"],
            ref_fuente=f"Pag {res['pag_inicio']}",
            embedding=vectores[i],
            metadata_info=meta
        )
        db.add(nuevo_bk)
        count_bloques += 1
            
    db.commit()
    print(f"=== INGESTA FINALIZADA: {count_bloques} fragmentos indexados ===")
    return {"mensaje": "Ingesta completa con chunking token-based", "bloques": count_bloques}