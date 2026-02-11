import json
import concurrent.futures
import textwrap
import os
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from fastapi import UploadFile
from pypdf import PdfReader
from io import BytesIO
from mistralai import Mistral

# Importamos modelos y servicios
from app.models.modelos import Temario, BaseConocimiento
from app.crud import rag_service

api_key = os.getenv("MISTRAL_API_KEY")
client = Mistral(api_key=api_key) if api_key else None

# ============================================================================
# 1. UTILIDADES DE EXTRACCIÓN (Limpio y sin limites)
# ============================================================================

def extraer_info_paginada(file: UploadFile) -> List[Dict[str, Any]]:
    """Lee el PDF y devuelve una lista de páginas limpia."""
    file.file.seek(0) # Asegurar lectura desde el inicio
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
                "numero": i + 1, # Base 1
                "text": "\n".join(lines)
            })
    return paginas

def obtener_texto_rango(paginas: List[Dict], inicio: int, fin: int) -> str:
    """Extrae texto de un rango de páginas."""
    texto_acumulado = ""
    # Si el fin es 0 o menor, leemos hasta el final real del array
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
# 2. FASE 1: ARQUITECTO (Estructura Jerárquica ESTRICTA)
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
        
        # Ordenar por orden de lectura (global) para mantener secuencia
        temas.sort(key=lambda x: x.get("orden_lectura", x.get("orden", 0)))
        
        print(f"--- Estructura detectada: {len(temas)} temas ---")
        return temas
    except Exception as e:
        print(f"Error generando estructura: {e}")
        return []

def _guardar_temario_recursivo(db: Session, temas: List[Dict]) -> List[Dict]:
    """Guarda en DB con ORDEN RELATIVO al padre.
    
    Ejemplo resultado:
      Tema 1 (nivel 1, orden 1, parent=None)
        Punto 1.1 (nivel 2, orden 1, parent=Tema1.id)
        Punto 1.2 (nivel 2, orden 2, parent=Tema1.id)
      Tema 2 (nivel 1, orden 2, parent=None)
        Punto 2.1 (nivel 2, orden 1, parent=Tema2.id)
    """
    lista_plana_db = []
    
    # Mapa: padres[nivel] = {"id": int, "nombre": str}
    padres = {}
    
    # Contadores de orden RELATIVO por parent_id
    # orden_por_padre[None] = contador para temas nivel 1 (raíz)
    # orden_por_padre[5] = contador para hijos del tema con id=5
    orden_por_padre = {}

    for t in temas:
        nivel_actual = t.get("nivel", 1)
        
        # Determinar padre
        parent_id = padres.get(nivel_actual - 1, {}).get("id") if nivel_actual > 1 else None
        parent_nombre = padres.get(nivel_actual - 1, {}).get("nombre", "") if nivel_actual > 1 else ""
        
        # Calcular orden RELATIVO al padre
        if parent_id not in orden_por_padre:
            orden_por_padre[parent_id] = 0
        orden_por_padre[parent_id] += 1
        orden_relativo = orden_por_padre[parent_id]
        
        # --- DEBUG VISUAL ---
        indent = "  " * (nivel_actual - 1)
        parent_str = f"(Hijo de '{parent_nombre}' id={parent_id})" if parent_id else "(RAIZ)"
        print(f"{indent}Guardando: {t['nombre']} - Nivel {nivel_actual}, Orden {orden_relativo} {parent_str} - Pag {t.get('pagina_inicio')}")
        # --------------------

        nuevo_tema = Temario(
            nombre=t["nombre"],
            nivel=nivel_actual,
            orden=orden_relativo,  # ORDEN RELATIVO AL PADRE
            parent_id=parent_id, 
            pagina_inicio=t.get("pagina_inicio", 0),
            descripcion=f"Tema de nivel {nivel_actual} importado",
            activo=True
        )
        db.add(nuevo_tema)
        db.commit()
        db.refresh(nuevo_tema)
        
        # Actualizo como el último padre vigente de mi nivel
        padres[nivel_actual] = {"id": nuevo_tema.id, "nombre": t["nombre"]}
        
        # Al cambiar de padre, resetear contadores de hijos
        # (Ej: si paso del cap 1 al cap 2, los hijos del cap 2 empiezan en orden 1)
        if nivel_actual + 1 in padres:
            del padres[nivel_actual + 1]
            # Limpiar contador de hijos del padre anterior de este nivel
            old_parent = padres.get(nivel_actual - 1, {}).get("id") if nivel_actual > 1 else None
            # No limpiar, el nuevo padre tendrá su propio contador

        # Guardar en lista para el siguiente paso
        t_con_id = t.copy()
        t_con_id["db_id"] = nuevo_tema.id
        t_con_id["parent_id"] = parent_id
        t_con_id["parent_nombre"] = parent_nombre
        t_con_id["orden"] = orden_relativo  # Sobreescribir con orden relativo
        lista_plana_db.append(t_con_id)
        
    return lista_plana_db

# ============================================================================
# 3. FASE 2: ATOMIZADOR DE CONTENIDO (Paralelo y Completo)
# ============================================================================

def dividir_texto_largo(texto: str, max_chars: int = 12000) -> List[str]:
    """Corta textos largos en trozos seguros para la IA."""
    if len(texto) <= max_chars: return [texto]
    return textwrap.wrap(texto, width=max_chars, break_long_words=False, replace_whitespace=False)

def procesar_chunk_ia(texto: str) -> List[Dict]:
    """Pregunta a la IA para clasificar texto/código."""
    if len(texto.strip()) < 10: return []
    
    prompt = """
    Analiza el texto del libro de programación.
    Divídelo en bloques JSON:
    - 'tipo': 'texto' (teoría) o 'codigo' (ejemplos python).
    - 'contenido': El texto LITERAL exacto.
    
    JSON: {"bloques": [{"tipo": "texto", "contenido": "..."}]}
    """
    try:
        resp = client.chat.complete(
            model="mistral-large-latest",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": texto}],
            response_format={"type": "json_object"}
        )
        return json.loads(resp.choices[0].message.content).get("bloques", [])
    except: return []

def tarea_procesar_tema(tema_info: Dict, texto_completo: str) -> Dict:
    """Función worker que se ejecuta en paralelo."""
    chunks = dividir_texto_largo(texto_completo)
    bloques_totales = []
    
    for chunk in chunks:
        bloques = procesar_chunk_ia(chunk)
        bloques_totales.extend(bloques)
        
    return {
        "tema_id": tema_info["db_id"],
        "nombre": tema_info["nombre"],
        "nivel": tema_info["nivel"],
        "orden": tema_info["orden"],             # Orden relativo al padre
        "parent_id": tema_info.get("parent_id"),
        "parent_nombre": tema_info.get("parent_nombre", ""),
        "pag_inicio": tema_info.get("pagina_inicio", 0),
        "bloques": bloques_totales,
        "error": None
    }

# ============================================================================
# 4. ORQUESTADOR PRINCIPAL
# ============================================================================

def procesar_archivo_temario(db: Session, file: UploadFile, account_id: str):
    print("=== INICIO DE INGESTA MEJORADA ===")
    
    # 1. Leer PDF (Todo el contenido)
    paginas_pdf = extraer_info_paginada(file)
    print(f" -> PDF leído: {len(paginas_pdf)} páginas detectadas.")
    
    # 2. Analizar Índice (Páginas 4 a 6 del libro 'Python para todos')
    # Extraemos texto suficiente para pillar todo el índice
    texto_indice = obtener_texto_rango(paginas_pdf, 4, 7) 
    
    # 3. Generar Estructura (IA)
    temas_raw = generar_estructura_temario(texto_indice)
    
    if not temas_raw:
        return {"error": "La IA no pudo detectar el índice."}

    # 4. Guardar Estructura en DB (Aquí se crean los padres e hijos)
    print(" -> Guardando jerarquía en base de datos...")
    temas_db = _guardar_temario_recursivo(db, temas_raw)
    
    # 5. Procesamiento de Contenido (Paralelo)
    print(f" -> Procesando contenido de {len(temas_db)} temas...")
    
    # Preparar datos para los workers
    temas_db.sort(key=lambda x: x.get("pagina_inicio", 0)) # Ordenar por pag
    tareas = []
    
    for i, tema in enumerate(temas_db):
        p_inicio = tema.get("pagina_inicio", 1)
        
        # Calcular fin: Inicio del siguiente tema o final del libro
        if i < len(temas_db) - 1:
            p_fin = temas_db[i+1].get("pagina_inicio", p_inicio)
        else:
            p_fin = len(paginas_pdf) + 1
            
        # Corregir lógica si p_fin es igual a p_inicio (tema de 1 pag)
        if p_fin <= p_inicio: p_fin = p_inicio + 1
            
        texto = obtener_texto_rango(paginas_pdf, p_inicio, p_fin)
        tareas.append((tema, texto))

    # Ejecutar
    resultados = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(tarea_procesar_tema, t, txt): t["db_id"] for t, txt in tareas}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if not res["error"]:
                resultados.append(res)
                print(f"   [OK] {res['nombre']} ({len(res['bloques'])} bloques)")

    # 6. Guardar Bloques y Embeddings
    print(" -> Insertando conocimientos y embeddings...")
    count_bloques = 0
    resultados.sort(key=lambda x: x["pag_inicio"]) # Guardar en orden
    
    for res in resultados:
        # Construir posición legible para Mistral
        # Ej: "Tema 2, punto 3" o "Colecciones > Listas (nivel 2, orden 1)"
        if res.get("parent_nombre"):
            posicion = f"{res['parent_nombre']} > {res['nombre']} (nivel {res['nivel']}, orden {res['orden']})"
        else:
            posicion = f"{res['nombre']} (nivel {res['nivel']}, orden {res['orden']})"
        
        # Metadatos COMPLETOS para que el RAG y Mistral sepan la jerarquía
        meta = {
            "titulo": res["nombre"],
            "nivel": res["nivel"],
            "orden": res["orden"],                # Orden relativo al padre
            "parent_id": res.get("parent_id"),     # ID del tema padre
            "parent_nombre": res.get("parent_nombre", ""),  # Nombre del padre
            "posicion": posicion,                  # "Colecciones > Listas (nivel 2, orden 1)"
            "origen": "ingesta_v2"
        }
        
        for idx, b in enumerate(res["bloques"]):
            tipo = b.get("tipo", "texto")
            contenido = b.get("contenido", "")
            
            # Embedding con contexto jerárquico
            txt_vector = f"[{posicion}]: {contenido}"
            vector = rag_service.generar_embedding(db, txt_vector)
            
            nuevo_bk = BaseConocimiento(
                temario_id=res["tema_id"],
                contenido=contenido,
                tipo_contenido=tipo,
                orden_aparicion=idx + 1,
                pagina=res["pag_inicio"],
                ref_fuente=f"Pag {res['pag_inicio']}",
                embedding=vector,
                metadata_info=meta  # Incluye parent_id, parent_nombre, posicion
            )
            db.add(nuevo_bk)
            count_bloques += 1
            
    db.commit()
    print("=== PROCESO FINALIZADO ===")
    return {"mensaje": "Ingesta completa con jerarquía", "bloques": count_bloques}