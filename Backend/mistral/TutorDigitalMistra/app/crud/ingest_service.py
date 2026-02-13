"""
Servicio de Ingesta de Documentos — Versión Final RAG Híbrido
- Soporte para Múltiples Libros (tabla 'libros')
- Lista Enlazada para Navegación Secuencial
- Chunking Token-Based
"""
import json
import os
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from fastapi import UploadFile
from pypdf import PdfReader
from io import BytesIO
from mistralai import Mistral

# Importamos modelos y servicios
from app.models.modelos import Temario, BaseConocimiento, Libro
from app.crud.embedding_service import generar_embeddings_batch
from app.crud.chunking_service import procesar_texto_tema

api_key = os.getenv("MISTRAL_API_KEY")
client = Mistral(api_key=api_key) if api_key else None

# ============================================================================
# 1. UTILIDADES DE EXTRACCIÓN PDF
# ============================================================================

def extraer_texto_pdf(contenido_bytes: bytes) -> Dict[int, str]:
    """Extrae texto de todas las páginas del PDF desde bytes."""
    pdf_file = BytesIO(contenido_bytes)
    pdf_reader = PdfReader(pdf_file)
    doc_completo = {}
    for i, pag in enumerate(pdf_reader.pages, start=1):
        txt = pag.extract_text() or ""
        # Limpieza básica
        txt = txt.replace("Python para todos", "").replace("Raúl González Duque", "")
        doc_completo[i] = txt.strip()
    return doc_completo

# ============================================================================
# 2. ANÁLISIS DE ESTRUCTURA (LLM)
# ============================================================================

def generar_estructura_temario(texto_indice: str) -> List[Dict]:
    """Usa Mistral para entender la jerarquía del índice."""
    if not client:
        print("⚠️ Advertencia: No hay API Key de Mistral. Usando modo dummy.")
        return []

    prompt = """
    Eres un experto bibliotecario. Tu tarea es convertir un Índice de contenidos (OCR) en una estructura JSON jerárquica.
    
    REGLAS:
    - Identifica capítulos (nivel 1) y secciones (nivel 2).
    - Extrae el número de página de inicio.
    - Mantén el orden de lectura correcto.
    
    JSON OUTPUT:
    {
        "temas": [
            {"nombre": "Título", "nivel": 1, "pagina_inicio": 5, "orden": 1},
            {"nombre": "Subtítulo", "nivel": 2, "pagina_inicio": 5, "orden": 2}
        ]
    }
    """
    
    try:
        response = client.chat.complete(
            model="mistral-large-latest",
            messages=[
                {"role": "system", "content": prompt}, 
                {"role": "user", "content": f"ÍNDICE:\n{texto_indice}"}
            ],
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content)
        return data.get("temas", [])
    except Exception as e:
        print(f"Error analizando índice: {e}")
        return []

# ============================================================================
# 3. PROCESO PRINCIPAL
# ============================================================================

def procesar_archivo_temario(db: Session, archivo_bytes: bytes, filename: str, account_id: str):
    """
    Flujo completo de ingestión con soporte para Libros y Lista Enlazada.
    """
    print("\n" + "="*80)
    print(f"PROCESANDO LIBRO: {filename}")
    print("="*80 + "\n")
    
    # 1. Crear registro de Libro
    try:
        print(" -> 1. Creando registro de LIBRO...")
        libro = Libro(
            titulo=filename.replace(".pdf", ""),
            descripcion=f"Subido el {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            pdf_path=f"uploads/{account_id}/{filename}",
            activo=True
        )
        db.add(libro)
        db.commit() # COMMIT INMEDIATO para asegurar que el libro existe
        db.refresh(libro)
        print(f"    ✅ [Libro ID: {libro.id}] Creado y commiteado exitosamente.")
    except Exception as e:
        print(f"    ❌ ERROR creando libro: {e}")
        return {"error": str(e)}

    # 2. Extraer texto
    try:
        print(" -> 2. Extrayendo texto del PDF...")
        doc_completo = extraer_texto_pdf(archivo_bytes)
        num_paginas = len(doc_completo)
        print(f"    ✅ {num_paginas} páginas extraídas.")
    except Exception as e:
        print(f"    ❌ ERROR extrayendo texto: {e}")
        return {"error": str(e)}
    
    if num_paginas == 0:
        print("    ⚠️ PDF vacío o ilegible.")
        return {"error": "PDF vacío"}

    try:
        # 3. Analizar índice (primeras 10 págs)
        print(" -> 3. Analizando estructura del índice...")
        texto_indice = "\n".join([doc_completo.get(i, "") for i in range(1, min(11, num_paginas))])
        try:
            temas_struct = generar_estructura_temario(texto_indice)
        except Exception as e:
            print(f"    ⚠️ Error en Mistral (Índice): {e}. Usando estructura por defecto.")
            temas_struct = []
        
        if not temas_struct:
            print("    Original index not found via AI. Creating default structure.")
            temas_struct = [{"nombre": "Contenido Completo", "nivel": 1, "pagina_inicio": 1, "orden": 1}]

        # 4. Guardar Temario en BD
        print(" -> 4. Guardando estructura del TEMARIO...")
        mapa_temario = {} # indice_lista -> objeto_db
        
        for i, t in enumerate(temas_struct):
            # Determinar padre (si nivel > 1, buscar el último de nivel-1)
            parent_id = None
            if t.get("nivel", 1) > 1:
                # Buscar hacia atrás el primer tema con nivel menor
                for prev_idx in range(i - 1, -1, -1):
                    if temas_struct[prev_idx].get("nivel", 1) < t.get("nivel", 1):
                        parent_id = mapa_temario[prev_idx].id
                        break
            
            nuevo_tema = Temario(
                libro_id=libro.id,
                parent_id=parent_id,
                nombre=t["nombre"],
                nivel=t.get("nivel", 1),
                orden=i + 1,
                pagina_inicio=t.get("pagina_inicio", 1),
                activo=True
            )
            db.add(nuevo_tema)
            db.flush()
            mapa_temario[i] = nuevo_tema

        db.commit()
        print(f"    ✅ {len(mapa_temario)} temas guardados.")

        # 5. Fragmentar y Crear Embeddings
        print(" -> 5. Procesando contenido y generando EMBEDDINGS...")
        
        todos_chunks = [] # Lista de tuplas (objeto_BaseConocimiento, texto_para_vector)
        
        # Iterar temas para asignar contenido
        for i in range(len(temas_struct)):
            # Log de progreso cada 5 temas para ver que avanza
            if i % 1 == 0: 
                print(f"    ... Procesando tema {i+1}/{len(temas_struct)} ({temas_struct[i]['nombre']})...")

            tema_actual = temas_struct[i]
            tema_db = mapa_temario[i]
            
            pag_inicio = tema_actual.get("pagina_inicio", 1)
            # Pag fin es el inicio del siguiente tema - 1, o el final del libro
            if i < len(temas_struct) - 1:
                pag_fin = temas_struct[i+1].get("pagina_inicio", num_paginas + 1) - 1
            else:
                pag_fin = num_paginas
                
            pag_fin = max(pag_inicio, pag_fin) # Evitar rangos negativos
            
            # Extraer texto del rango de páginas
            texto_tema = ""
            for p in range(pag_inicio, pag_fin + 1):
                texto_tema += doc_completo.get(p, "") + "\n"
                
            if not texto_tema.strip():
                continue
                
            # Calcular nombre del padre si existe
            nombre_padre = ""
            
            bloques = procesar_texto_tema(
                texto=texto_tema,
                nombre_tema=tema_actual["nombre"],
                nivel=tema_actual.get("nivel", 1),
                orden=tema_actual.get("orden", 1),
                pagina_inicio=pag_inicio,
                parent_nombre=nombre_padre
            )
            
            for bloque in bloques:
                meta = bloque["metadata"]
                
                # Pre-crear objeto (sin IDs de enlace aún)
                chunk_obj = BaseConocimiento(
                    temario_id=tema_db.id,
                    contenido=bloque["contenido"],
                    tipo_contenido=bloque["tipo"], # 'texto' o 'codigo'
                    pagina=pag_inicio, # Aproximado
                    ref_fuente=f"Pág {pag_inicio}",
                    metadata_info={
                        "titulo_tema": tema_actual["nombre"],
                        **meta
                    }
                )
                # Texto para embedding: Contextualizado
                texto_vector = f"[{tema_actual['nombre']}]: {bloque['contenido']}"
                todos_chunks.append((chunk_obj, texto_vector))

        print(f"    Total chunks generados: {len(todos_chunks)}")
        
        if not todos_chunks:
            print("    ⚠️ No se generaron chunks. Verifica el contenido del PDF.")
            return {"error": "No chunks generated"}

        # 6. Generar Embeddings en Batch
        print(" -> 6. Llamando a OpenAI Embeddings (Batch)...")
        textos_batch = [item[1] for item in todos_chunks]
        vectores = generar_embeddings_batch(db, textos_batch)
        
        # 7. Guardar con Lista Enlazada (por lotes para evitar timeouts/db errors)
        print(" -> 7. Guardando en BaseConocimiento (Batch con Row-by-Row Fallback)...")
        
        chunks_guardados = []
        
        # Batch size
        BATCH_FLUSH = 10
        chunks_batch = []
        
        for i, (chunk_obj, _) in enumerate(todos_chunks):
            # Validar Embedding (evitar NaN)
            vec = vectores[i]
            if vec is None:
                vec = []

            # --- FIX: Convertir explícitamente a lista de Python para evitar problemas con NumPy ---
            if hasattr(vec, "tolist"):
                vec = vec.tolist()
            elif isinstance(vec, (tuple, range)):
                vec = list(vec)
            
            # Si es None o vacío, vector cero
            if not vec or len(vec) == 0:
                 print(f"    ⚠️ Embedding vacío/None en chunk {i}. Se usará vector cero.")
                 vec = [0.0] * 1536
            
            # Check for NaNs safely (ahora seguro porque es lista)
            if any(x != x for x in vec): # x!=x detecta NaN
                  print(f"    ⚠️ Embedding corrupto (NaN) en chunk {i}. Se usará vector cero.")
                  vec = [0.0] * 1536

            chunk_obj.embedding = vec
            chunk_obj.orden_aparicion = i + 1
            chunks_batch.append(chunk_obj)
            chunks_guardados.append(chunk_obj)
            
            # Flush cada N
            if len(chunks_batch) >= BATCH_FLUSH:
                try:
                    db.add_all(chunks_batch)
                    db.flush()
                except Exception as e:
                    print(f"       ⚠️ Error en Batch Flush (chunk {i-BATCH_FLUSH}-{i}): {e}. Trying Row-by-Row...")
                    db.rollback()
                    # Reintentar uno por uno
                    for c in chunks_batch:
                        try:
                            # Re-add porque rollback lo detachó
                            db.add(c)
                            db.flush()
                        except Exception as e_row:
                            print(f"       ❌ Skipping Chunk Corrupto (orden {c.orden_aparicion}): {e_row}")
                            db.rollback() # Skip this row
                            chunks_guardados.remove(c) # No lo contamos
                finally:
                    chunks_batch = [] # Reset batch
        
        # Flush final para los restantes
        if chunks_batch:
            try:
                db.add_all(chunks_batch)
                db.flush()
            except Exception as e:
                 print(f"       ⚠️ Error en Último Batch Flush: {e}. Trying Row-by-Row...")
                 db.rollback()
                 for c in chunks_batch:
                    try:
                        db.add(c)
                        db.flush()
                    except Exception as e_row:
                        print(f"       ❌ Skipping Chunk Corrupto (orden {c.orden_aparicion}): {e_row}")
                        db.rollback()
                        chunks_guardados.remove(c) 

        # Establecer enlaces (Anterior / Siguiente)
        print(" -> 7b. Estableciendo enlaces...")
        try:
            for i in range(len(chunks_guardados)):
                current = chunks_guardados[i]
                if i > 0:
                    current.chunk_anterior_id = chunks_guardados[i-1].id
                if i < len(chunks_guardados) - 1:
                    current.chunk_siguiente_id = chunks_guardados[i+1].id
            db.commit()
        except Exception as e_link:
             print(f"    ⚠️ Error linking chunks (non-critical): {e_link}")
             # Intentar al menos salvar los chunks sin links
             db.rollback()
        
        print("\n" + "="*80)
        print(f"PROCESO TERMINADO EXITOSAMENTE")
        print(f"Libro: {libro.titulo}")
        print(f"Chunks indexados: {len(chunks_guardados)}")
        print("="*80 + "\n")
        
        return {
            "mensaje": "Libro procesado correctamente",
            "libro_id": libro.id,
            "bloques": len(chunks_guardados)
        }

    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        print(f"    ❌ CRITICAL ERROR en proceso de ingestión: {e}")
        return {"error": str(e)}