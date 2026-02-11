import json
import concurrent.futures
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from fastapi import UploadFile
from pypdf import PdfReader
from io import BytesIO
from mistralai import Mistral
import os

# Importamos modelos y el servicio de RAG
from app.models.modelos import Temario, BaseConocimiento
from app.crud import rag_service

api_key = os.getenv("MISTRAL_API_KEY")
client = Mistral(api_key=api_key) if api_key else None

# ============================================================================
# 1. UTILIDADES DE EXTRACCIÓN (Sin cambios)
# ============================================================================

def extraer_info_paginada(file: UploadFile) -> List[Dict[str, Any]]:
    content = file.file.read()
    reader = PdfReader(BytesIO(content))
    paginas = []
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
    texto_acumulado = ""
    # Ajuste para capturar correctamente el rango
    for p in paginas:
        if inicio <= p["numero"] < fin: 
            texto_acumulado += p["text"] + "\n\n"
    if inicio == fin: # Caso borde: tema de una sola página
         for p in paginas:
            if p["numero"] == inicio:
                texto_acumulado += p["text"]
    return texto_acumulado

# ============================================================================
# 2. FASE 1: ARQUITECTO (Estructura) - Se mantiene secuencial (es rápido)
# ============================================================================

def generar_estructura_temario(texto_indice: str) -> List[Dict]:
    if not client: return []
    prompt = """
    ERES UN EDITOR. Extrae la estructura del libro en JSON.
    REGLAS: 'nombre', 'nivel' (1, 2), 'pagina_inicio'.
    FORMATO JSON: {"temas": [{"nombre": "...", "nivel": 1, "orden": 1, "pagina_inicio": 7}, ...]}
    """
    try:
        response = client.chat.complete(
            model="mistral-large-latest",
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": texto_indice}],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content).get("temas", [])
    except: return []

def _guardar_temario_recursivo(db: Session, temas: List[Dict]) -> List[Dict]:
    lista_plana = []
    padres = {} 
    
    for t in temas:
        nivel = t.get("nivel", 1)
        parent_id = padres.get(nivel - 1) if nivel > 1 else None
        
        nuevo_tema = Temario(
            nombre=t["nombre"], nivel=nivel, orden=t.get("orden", 0),
            parent_id=parent_id, pagina_inicio=t.get("pagina_inicio", 0),
            descripcion="Tema importado"
        )
        db.add(nuevo_tema)
        db.commit()
        db.refresh(nuevo_tema)
        padres[nivel] = nuevo_tema.id
        
        t_con_id = t.copy()
        t_con_id["db_id"] = nuevo_tema.id
        lista_plana.append(t_con_id)
        
    return lista_plana

# ============================================================================
# 3. FASE 2: ATOMIZADOR PARALELO (Aquí está la magia de la velocidad)
# ============================================================================

def procesar_texto_con_ia(tema_id: int, texto: str, pag_inicio: int) -> Dict:
    """
    Esta función NO toca la base de datos. Solo habla con la IA.
    Esto permite ejecutarla en hilos paralelos sin corromper SQLAlchemy.
    """
    if not texto or len(texto) < 10: 
        return {"tema_id": tema_id, "bloques": [], "error": "Texto vacío"}

    prompt = """
    DIVIDE EL TEXTO EN BLOQUES SECUENCIALES.
    1. NO RESUMAS. Usa texto literal.
    2. 'tipo': 'texto' o 'codigo'.
    JSON: {"bloques": [{"tipo": "texto", "contenido": "..."}]}
    """
    try:
        # Nota: Si Mistral da error 429 (Rate Limit), el retry del cliente lo manejará
        # o habrá que reducir max_workers en el ThreadPool.
        resp = client.chat.complete(
            model="mistral-large-latest",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"TEXTO:\n{texto[:12000]}"} # Recorte preventivo
            ],
            response_format={"type": "json_object"}
        )
        bloques = json.loads(resp.choices[0].message.content).get("bloques", [])
        return {"tema_id": tema_id, "pag_inicio": pag_inicio, "bloques": bloques, "error": None}
    except Exception as e:
        return {"tema_id": tema_id, "error": str(e)}

def procesar_archivo_temario(db: Session, file: UploadFile, account_id: str = None):
    print("--- INICIO PROCESO DE ALTA VELOCIDAD ---")
    
    # 1. Leer PDF
    paginas_pdf = extraer_info_paginada(file)
    
    # 2. Estructura (Índice)
    texto_indice = obtener_texto_rango(paginas_pdf, 1, 15)
    estructura = generar_estructura_temario(texto_indice)
    if not estructura: return {"error": "Fallo al leer índice"}
    
    # 3. Guardar esqueleto en BD (Esto es rápido)
    temas_db = _guardar_temario_recursivo(db, estructura)
    temas_db.sort(key=lambda x: x.get("pagina_inicio", 0))
    
    # 4. PREPARAR TAREAS PARALELAS
    # En lugar de procesar, preparamos los datos necesarios para cada hilo
    tareas_ia = []
    
    for i, tema in enumerate(temas_db):
        p_inicio = tema.get("pagina_inicio", 1)
        if i < len(temas_db) - 1:
            p_fin = temas_db[i+1].get("pagina_inicio", p_inicio)
        else:
            p_fin = len(paginas_pdf) + 1
        
        if p_fin <= p_inicio: p_fin = p_inicio + 1
        
        texto_capitulo = obtener_texto_rango(paginas_pdf, p_inicio, p_fin)
        
        # Guardamos los argumentos para la función paralela
        tareas_ia.append({
            "tema_id": tema["db_id"],
            "texto": texto_capitulo,
            "pag_inicio": p_inicio
        })

    print(f" -> Lanzando {len(tareas_ia)} tareas en paralelo...")

    # 5. EJECUCIÓN PARALELA (ThreadPool)
    # Ajusta max_workers según tu plan de API (3-5 suele ser seguro, 10 es muy rápido pero arriesgado)
    resultados_procesados = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # Mapeamos la función a los argumentos
        futures = {executor.submit(procesar_texto_con_ia, t["tema_id"], t["texto"], t["pag_inicio"]): t for t in tareas_ia}
        
        for future in concurrent.futures.as_completed(futures):
            resultado = future.result()
            if not resultado.get("error"):
                resultados_procesados.append(resultado)
                print(f"   [OK] Tema ID {resultado['tema_id']} procesado.")
            else:
                print(f"   [ERROR] Tema ID {resultado['tema_id']}: {resultado['error']}")

    # 6. GUARDADO EN BD (SECUENCIAL Y SEGURO)
    # Ahora que tenemos todos los datos, los guardamos en la BD en el hilo principal
    print(" -> Guardando bloques en base de datos...")
    total_bloques = 0
    
    for item in resultados_procesados:
        tema_id = item["tema_id"]
        pag_base = item["pag_inicio"]
        
        for idx, b in enumerate(item["bloques"]):
            tipo = b.get("tipo", "texto")
            contenido = b.get("contenido", "")
            
            # Generamos embedding (puede tardar un poco, pero ya ahorramos mucho tiempo antes)
            # Opcional: Podrías paralelizar esto también, pero cuidado con rate limits de embeddings
            vector = rag_service.generar_embedding(db, f"{tipo.upper()}: {contenido}")
            
            nuevo_bloque = BaseConocimiento(
                temario_id=tema_id,
                contenido=contenido,
                tipo_contenido=tipo,
                orden_aparicion=idx + 1,
                pagina=pag_base,
                ref_fuente=f"Libro Pag {pag_base}",
                embedding=vector,
                metadata_info={"origen": "ingesta_paralela"}
            )
            db.add(nuevo_bloque)
            total_bloques += 1
            
    db.commit()
    print("--- FIN PROCESO ---")
    
    return {"mensaje": "Procesamiento paralelo completado", "bloques": total_bloques}