import logging
import os
import io
import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
import pandas as pd
import google.generativeai as genai
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.services.dataverse import DataverseClient
# Importamos el nuevo servicio multipestaña
# Importamos el nuevo servicio
from app.services.excel_multipestanas_service import process_pricing_excel

# Configuración de Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gestion", tags=["Gestión de Productos"])

# Configurar Gemini (usa la key del .env)
try:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
        logger.info("✅ Gemini IA configurada.")
    else:
        logger.warning("⚠️ Sin API Key.")
except Exception as e:
    logger.warning(f"⚠️ Error Gemini: {e}")

# ═══════════════════════════════════════════════════════════════
# MODELOS PYDANTIC
# ═══════════════════════════════════════════════════════════════

class ComercializadoraResponse(BaseModel):
    id: str
    nombre: str
    nif: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    activa: bool
    total_productos: int = 0

class ComercializadoraCreate(BaseModel):
    nombre: str
    nif: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    activa: bool = True

# ═══════════════════════════════════════════════════════════════
# 🕵️♂️ PLAN B: PARSER MANUAL (SOLO TARIFAS)
# ═══════════════════════════════════════════════════════════════

def parser_rescate_manual(df: pd.DataFrame) -> List[Dict]:
    """Busca filas que contengan una tarifa válida (2.0TD, RL.1...)"""
    logger.info("⚠️ MODO MANUAL: Buscando tarifas y nombres...")
    productos = []
    
    # Patrón de tarifas comunes
    regex_tarifa = r'(2\.0TD|3\.0TD|6\.1TD|6\.2TD|RL\.1|RL\.2|RL\.3|RL\.4)'
    
    for idx, row in df.iterrows():
        # Convertimos la fila a texto mayúsculas
        fila_str = " ".join([str(x) for x in row if pd.notna(x)]).upper()
        
        # ¿Contiene alguna tarifa?
        match = re.search(regex_tarifa, fila_str)
        if match:
            tarifa = match.group(1)
            
            # Buscar el nombre (el texto más largo que no sea la tarifa)
            nombre = "TARIFA SIN NOMBRE"
            textos = [str(x) for x in row if pd.notna(x) and len(str(x)) > 4]
            
            # Filtramos textos basura
            candidatos = [
                t for t in textos 
                if tarifa not in t 
                and not re.match(r'^[\d\.,]+$', t) # No es solo números
                and "PRECIO" not in t.upper()
            ]
            
            if candidatos:
                # Nos quedamos con el más largo (suele ser la descripción)
                nombre = max(candidatos, key=len)

            # Guardamos SIEMPRE, precio 0 por defecto
            productos.append({
                "codigo": f"MAN-{idx}",
                "nombre": nombre,
                "tarifa": tarifa,
                "precio": 0.0
            })
                
    return productos

# ═══════════════════════════════════════════════════════════════
# 🧠 PLAN A: CEREBRO IA (Instrucción Simplificada)
# ═══════════════════════════════════════════════════════════════

def analizar_excel_con_gemini(contenido: bytes, filename: str) -> List[Dict]:
    logger.info(f"🤖 Procesando: {filename}")
    try:
        xls = pd.ExcelFile(io.BytesIO(contenido), engine='openpyxl')
        texto_para_ia = ""
        df_completo = pd.DataFrame()

        # Leemos hojas
        for nombre_hoja in xls.sheet_names:
            try:
                # Saltamos hojas irrelevantes
                if "PORTADA" in nombre_hoja.upper(): continue
                
                df = pd.read_excel(xls, sheet_name=nombre_hoja, header=None)
                df_limpio = df.dropna(how='all')
                df_completo = pd.concat([df_completo, df_limpio])

                if not df_limpio.empty:
                    texto_para_ia += f"\n--- HOJA {nombre_hoja} ---\n"
                    # Pasamos más filas para asegurar
                    texto_para_ia += df_limpio.head(200).to_csv(index=False, header=False)
            except: pass

        if not texto_para_ia: return []

        # --- INTENTO 1: IA GEMINI ---
        prompt = f"""
        Analiza este CSV de energía. Tu único objetivo es LISTAR PRODUCTOS.
        
        REGLAS:
        1. Busca filas que mencionen una TARIFA (2.0TD, 3.0TD, RL.1, RL.2...).
        2. Extrae el NOMBRE comercial del plan.
        3. El PRECIO NO IMPORTA. Pon siempre 0 si no es obvio.
        4. Inventa un CODIGO si no existe.
        
        JSON:
        [
            {{"codigo": "E1", "nombre": "Plan Fijo", "tarifa": "2.0TD", "precio": 0}},
            {{"codigo": "G1", "nombre": "Gas Mini", "tarifa": "RL.1", "precio": 0}}
        ]
        
        Datos:
        {texto_para_ia[:30000]}
        """
        
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(prompt)
            texto_limpio = response.text.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\[.*\]', texto_limpio, re.DOTALL)
            
            if match:
                datos = json.loads(match.group(0))
                if len(datos) > 0:
                    return datos
        except Exception as e:
            logger.error(f"❌ IA falló: {e}")

        # --- PLAN B (MANUAL) ---
        return parser_rescate_manual(df_completo)

    except Exception as e:
        logger.error(f"❌ Error archivo: {e}")
        return []

# ═══════════════════════════════════════════════════════════════
# 📄 PARSER INTELIGENTE MULTI-FORMATO (PDF, CSV, Excel)
# ═══════════════════════════════════════════════════════════════

def extraer_texto_pdf(contenido: bytes) -> str:
    """Extrae texto de un PDF preservando la estructura"""
    try:
        from pypdf import PdfReader
        pdf_reader = PdfReader(io.BytesIO(contenido))
        texto_completo = ""
        
        for i, page in enumerate(pdf_reader.pages):
            texto_completo += f"\n--- PÁGINA {i+1} ---\n"
            texto_completo += page.extract_text()
        
        logger.info(f"📄 PDF extraído: {len(texto_completo)} caracteres")
        return texto_completo
    except Exception as e:
        logger.error(f"Error extrayendo PDF: {e}")
        return ""

def parsear_csv_con_secciones(contenido: bytes) -> List[Dict]:
    """
    Parser especializado para CSVs donde las tarifas son cabeceras de sección.
    
    Estructura esperada:
    - Fila N: "TARIFA 2.0TD" o solo "2.0TD"
    - Fila N+1...M: Productos bajo esa tarifa
    - Fila M+1: "TARIFA 3.0TD" (nueva sección)
    """
    logger.info("🔧 Parser CSV con secciones de tarifas")
    productos = []
    productos_unicos = set()  # Control de duplicados
    
    try:
        # Leer el CSV sin asumir estructura de columnas
        df = pd.read_csv(io.BytesIO(contenido), header=None, encoding='utf-8', on_bad_lines='skip')
        logger.info(f"   📊 Total de filas en CSV: {len(df)}")
        
        regex_tarifa = r'\b(2\.0TD|2\.0DHA|2\.0DHS|3\.0\s?TD|3\.0TDVE|6\.[1-6]TD|RL\.[1-4])\b'
        current_tariff = None
        
        for idx, row in df.iterrows():
            # Convertir fila a texto
            fila_texto = " ".join([str(x) for x in row if pd.notna(x)]).strip()
            
            if not fila_texto or len(fila_texto) < 2:
                continue
            
            # ¿Es una cabecera de tarifa?
            if re.search(r'^(TARIFA\s+)?(' + regex_tarifa[2:-2] + r')\s*$', fila_texto, re.IGNORECASE):
                match = re.search(regex_tarifa, fila_texto, re.IGNORECASE)
                if match:
                    current_tariff = match.group(1).upper().replace(" ", "")  # Normalizar "3.0 TD" -> "3.0TD"
                    logger.info(f"   📌 Sección tarifa detectada: {current_tariff}")
                continue
            
            # ¿Contiene una tarifa explícita en la línea?
            match_tarifa = re.search(regex_tarifa, fila_texto, re.IGNORECASE)
            tarifa_a_usar = None
            
            if match_tarifa:
                tarifa_a_usar = match_tarifa.group(1).upper().replace(" ", "")
            elif current_tariff:
                tarifa_a_usar = current_tariff
            
            # Si tenemos tarifa, intentar extraer el nombre del producto
            if tarifa_a_usar:
                # Buscar el nombre en las celdas de la fila
                nombre_candidatos = []
                
                for celda in row:
                    if pd.notna(celda):
                        celda_str = str(celda).strip()
                        
                        # CRITERIOS MÁS PERMISIVOS
                        # - Al menos 1 caracter
                        # - Contiene al menos una letra
                        # - No es la tarifa misma
                        # - No es solo números/puntos/comas
                        if (len(celda_str) >= 1 and  # Aceptar cualquier longitud
                            re.search(r'[a-zA-ZñÑáéíóúÁÉÍÓÚ]', celda_str) and  # Tiene letras
                            not re.match(r'^[\d\.,\s]+$', celda_str) and  # No es solo números
                            celda_str.upper() != tarifa_a_usar):  # No es la tarifa
                            
                            # Filtrar keywords obvias de no-producto
                            keywords_exclusion = ['PRECIO', 'TARIFA', 'P1', 'P2', 'P3', 'P4', 'P5', 'P6', 
                                                 'KWH', '€/KWH', 'TERMINO', 'POTENCIA', 'ENERGIA']
                            
                            if not any(kw in celda_str.upper() for kw in keywords_exclusion):
                                nombre_candidatos.append(celda_str)
                
                if nombre_candidatos:
                    # Tomar el candidato más largo (suele ser el nombre del producto)
                    nombre_base = max(nombre_candidatos, key=len)
                    nombre_final = f"{nombre_base} ({tarifa_a_usar})"
                    
                    # Evitar duplicados exactos
                    clave_unica = nombre_final.lower()
                    if clave_unica not in productos_unicos:
                        productos_unicos.add(clave_unica)
                        productos.append({
                            "codigo": f"CSV-{len(productos)+1}-{int(datetime.now().timestamp())}",
                            "nombre": nombre_final,
                            "tarifa": tarifa_a_usar,
                            "precio": 0.0
                        })
                        logger.info(f"   ✓ Producto {len(productos)}: {nombre_final}")
                else:
                    # Debug: mostrar filas que tienen tarifa pero no nombre válido
                    logger.debug(f"   ⚠️ Fila {idx} con tarifa {tarifa_a_usar} pero sin nombre válido: {fila_texto[:50]}")
        
        logger.info(f"   ✅ Parser CSV: {len(productos)} productos únicos detectados")
        return productos
        
    except Exception as e:
        logger.error(f"Error en parser CSV con secciones: {e}", exc_info=True)
        return []

def extraer_texto_estructurado(contenido: bytes, filename: str) -> str:
    """
    Convierte Excel/CSV a texto estructurado preservando secciones.
    Esto permite que el LLM vea cabeceras como "2.0TD" separadas de productos.
    """
    try:
        # Detectar si es CSV o Excel
        if filename.lower().endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contenido), header=None, encoding='utf-8', on_bad_lines='skip')
            texto = "--- ARCHIVO CSV ---\n"
            texto += df.head(300).to_csv(index=False, header=False)
            return texto
        else:
            # Excel
            xls = pd.ExcelFile(io.BytesIO(contenido), engine='openpyxl')
            texto_completo = ""
            
            for nombre_hoja in xls.sheet_names:
                if "PORTADA" in nombre_hoja.upper():
                    continue
                    
                try:
                    df = pd.read_excel(xls, sheet_name=nombre_hoja, header=None)
                    df_limpio = df.dropna(how='all')
                    
                    if not df_limpio.empty:
                        texto_completo += f"\n--- HOJA: {nombre_hoja} ---\n"
                        texto_completo += df_limpio.head(300).to_csv(index=False, header=False)
                except:
                    pass
            
            return texto_completo
    except Exception as e:
        logger.error(f"Error extrayendo Excel/CSV: {e}")
        return ""

def prompt_extraccion_inteligente(texto_datos: str) -> str:
    """Retorna el prompt mejorado que enseña al LLM a detectar tarifas en secciones"""
    return f"""
Eres un experto en tarifas energéticas de España. Tu misión es extraer productos de este documento.

**REGLAS CRÍTICAS DE PARSING:**

1. **DETECCIÓN DE TARIFAS SECCIONALES:**
   - Si encuentras una línea que SOLO contiene una tarifa (ej: "2.0TD", "TARIFA 2.0TD", "3.0TDVE"), 
     esa tarifa se aplica a TODOS los productos siguientes hasta que aparezca otra tarifa.
   - Ejemplo:
     ```
     2.0TD              ← Esta es una cabecera de sección
     TERRA AIR 24h      ← Este producto tiene tarifa 2.0TD
     FÁCIL ON           ← Este también tiene 2.0TD
     3.0TD              ← Nueva cabecera
     PLAN EMPRESA       ← Este tiene 3.0TD
     ```

2. **EXTRACCIÓN DE NOMBRE:**
   - Extrae el NOMBRE COMERCIAL COMPLETO del producto
   - Ejemplos: "TERRA AIR 24h KIT! 11", "FÁCIL ON", "Plan Indexado Plus"
   - NO incluyas la tarifa en el nombre a menos que sea parte del branding

3. **TARIFAS VÁLIDAS (España):**
   - Electricidad: 2.0TD, 2.0DHA, 2.0DHS, 3.0TD, 3.0TDVE, 6.1TD, 6.2TD, 6.3TD, 6.4TD
   - Gas: RL.1, RL.2, RL.3, RL.4

4. **PRECIO:**
   - Si encuentras un precio obvio (€/kWh), extráelo
   - Si NO hay precio claro, pon 0.0
   - NO inventes precios

5. **CÓDIGO:**
   - Si existe un código/SKU, úsalo
   - Si no, genera uno como "AUTO-1", "AUTO-2"

**FORMATO DE SALIDA (JSON ESTRICTO):**
```json
[
  {{"codigo": "AUTO-1", "nombre": "TERRA AIR 24h KIT! 11", "tarifa": "2.0TD", "precio": 0.171}},
  {{"codigo": "AUTO-2", "nombre": "FÁCIL ON", "tarifa": "2.0TD", "precio": 0.099}},
  {{"codigo": "AUTO-3", "nombre": "Plan Empresa Plus", "tarifa": "3.0TD", "precio": 0.0}}
]
```

**DATOS A PROCESAR:**
{texto_datos[:35000]}

RESPONDE SOLO CON EL JSON ARRAY. NO AGREGUES EXPLICACIONES.
"""

def parser_manual_con_secciones(texto: str) -> List[Dict]:
    """Parser de rescate que detecta secciones de tarifas - VERSIÓN MEJORADA"""
    logger.info("⚠️ FALLBACK: Parser manual con secciones")
    productos = []
    productos_unicos = set()  # Para evitar duplicados
    
    regex_tarifa = r'\b(2\.0TD|2\.0DHA|2\.0DHS|3\.0TD|3\.0TDVE|6\.[1-4]TD|RL\.[1-4])\b'
    
    lineas = texto.split('\n')
    tarifa_actual = None
    
    for idx, linea in enumerate(lineas):
        linea_strip = linea.strip()
        if not linea_strip or len(linea_strip) < 3:
            continue
        
        # ¿Es una línea que solo contiene tarifa? (cabecera de sección)
        match_solo = re.match(r'^(?:TARIFA\s+)?(' + regex_tarifa[2:-2] + r')$', linea_strip, re.IGNORECASE)
        if match_solo:
            tarifa_actual = match_solo.group(1).upper()
            logger.info(f"   📌 Sección detectada: {tarifa_actual}")
            continue
        
        # ¿La línea contiene una tarifa?
        match_tarifa = re.search(regex_tarifa, linea, re.IGNORECASE)
        if match_tarifa or tarifa_actual:
            # Usar tarifa de la línea o la sección actual
            tarifa_linea = match_tarifa.group(1).upper() if match_tarifa else tarifa_actual
            
            # MEJORA: Extraer nombre de forma más flexible
            # Intentamos separar por comas, tabulaciones, o múltiples espacios
            separadores = [',', '\t', '  ']
            partes = [linea_strip]
            for sep in separadores:
                if sep in linea_strip:
                    partes = linea_strip.split(sep)
                    break
            
            nombre = "Producto detectado"
            
            # Buscar el nombre en las partes (MENOS RESTRICTIVO)
            for parte in partes:
                parte_clean = parte.strip()
                # Condiciones más flexibles:
                # - Al menos 1 letra
                # - No sea SOLO la tarifa
                # - No sea SOLO números
                if (len(parte_clean) >= 1 and  # Aceptar incluso nombres de 1 letra
                    re.search(r'[a-zA-ZñÑáéíóúÁÉÍÓÚ]', parte_clean) and  # Contiene letras (incluye español)
                    not re.match(r'^[\d\.,\s]+$', parte_clean) and  # No es solo números y espacios
                    parte_clean.upper() != tarifa_linea and  # No es solo la tarifa
                    'PRECIO' not in parte_clean.upper() and
                    'P1' not in parte_clean.upper() and  # Filtrar términos de precios
                    'P2' not in parte_clean.upper() and
                    'P3' not in parte_clean.upper() and
                    'P4' not in parte_clean.upper() and
                    'P5' not in parte_clean.upper() and
                    'P6' not in parte_clean.upper()):
                    
                    # Limpiar el nombre de caracteres extraños
                    nombre = re.sub(r'\s+', ' ', parte_clean).strip()
                    if len(nombre) > 0:
                        break
            
            # Solo agregar si tiene tarifa válida y nombre no genérico
            if tarifa_linea:
                # Crear clave única para detectar duplicados
                clave_unica = f"{nombre.lower()}_{tarifa_linea}"
                
                if clave_unica not in productos_unicos:
                    productos_unicos.add(clave_unica)
                    productos.append({
                        "codigo": f"MAN-{len(productos)+1}-{int(datetime.now().timestamp())}",
                        "nombre": nombre,
                        "tarifa": tarifa_linea,
                        "precio": 0.0
                    })
    
    logger.info(f"   🔧 Parser manual encontró: {len(productos)} productos únicos")
    return productos

def analizar_archivo_inteligente(contenido: bytes, filename: str) -> List[Dict]:
    """
    Parser universal que maneja PDF, Excel y CSV con tarifas seccionales.
    
    Returns:
        Lista de productos: [{"codigo": "...", "nombre": "...", "tarifa": "2.0TD", "precio": 0.0}]
    """
    logger.info(f"🤖 PARSER INTELIGENTE: {filename}")
    
    try:
        # PASO PRIORITARIO: Si es CSV, usar el parser especializado de secciones
        if filename.lower().endswith('.csv'):
            logger.info("   📊 Intentando parser CSV especializado...")
            productos_csv = parsear_csv_con_secciones(contenido)
            if len(productos_csv) > 0:
                logger.info(f"   ✅ Parser CSV exitoso: {len(productos_csv)} productos")
                return productos_csv
            logger.info("   ⚠️ Parser CSV no detectó productos, probando IA...")
        
        # PASO 1: Extracción de texto según formato
        texto_datos = ""
        
        if filename.lower().endswith('.pdf'):
            logger.info("   📄 Formato: PDF")
            texto_datos = extraer_texto_pdf(contenido)
        elif filename.lower().endswith(('.xlsx', '.xls', '.csv')):
            logger.info("   📊 Formato: Excel/CSV")
            texto_datos = extraer_texto_estructurado(contenido, filename)
        else:
            logger.warning(f"   ⚠️ Formato desconocido: {filename}")
            return []
        
        if not texto_datos or len(texto_datos) < 50:
            logger.warning("   ⚠️ Texto extraído vacío o muy corto")
            return []
        
        # PASO 2: Análisis con LLM (Gemini)
        try:
            logger.info("   🧠 Enviando a Gemini...")
            prompt = prompt_extraccion_inteligente(texto_datos)
            
            model = genai.GenerativeModel('gemini-1.5-flash-latest')
            response = model.generate_content(prompt)
            
            # Limpiar y extraer JSON
            texto_respuesta = response.text.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\[.*\]', texto_respuesta, re.DOTALL)
            
            if match:
                productos = json.loads(match.group(0))
                if len(productos) > 0:
                    logger.info(f"   ✅ Gemini extrajo {len(productos)} productos")
                    return productos
            
            logger.warning("   ⚠️ Gemini no retornó JSON válido")
        
        except Exception as e:
            logger.error(f"   ❌ Error con Gemini: {e}")
        
        # PASO 3: Fallback a parser manual con secciones
        logger.info("   🔧 Intentando parser manual...")
        productos = parser_manual_con_secciones(texto_datos)
        
        if len(productos) > 0:
            return productos
        
        logger.warning("   ❌ No se pudieron extraer productos")
        return []
    
    except Exception as e:
        logger.error(f"❌ Error fatal en parser: {e}", exc_info=True)
        return []

# ═══════════════════════════════════════════════════════════════
# ENDPOINTS: COMERCIALIZADORAS
# ═══════════════════════════════════════════════════════════════

COMERCIALIZADORAS_RELEVANTES = [
    "Repsol", "TotalEnergies", "Total Energies", "Endesa", "Iberdrola", 
    "Naturgy", "Gana Energia", "Gana Energía", "EDP", "Holaluz", "Podo", 
    "Eleia", "Energia Elèctrica Catalana", "Audax", "Som Energia", 
    "Factor Energia", "Lucera", "Octopus Energy"
]

@router.get("/comercializadoras", response_model=List[ComercializadoraResponse])
async def listar_comercializadoras_gestion():
    """Lista comercializadoras relevantes"""
    try:
        dv = DataverseClient()
        logger.info("🔍 Buscando comercializadoras relevantes...")
        
        comercializadoras_candidatas = dv.query(
            entity='accounts',
            filter_query='statecode eq 0 and accountcategorycode eq 1',
            select_fields=['accountid', 'name', 'telephone1', 'emailaddress1', 'accountcategorycode'],
            top=500
        )
        
        ids_existentes = {c['accountid'] for c in comercializadoras_candidatas}
        
        for nombre in COMERCIALIZADORAS_RELEVANTES:
            try:
                safe_nombre = nombre.replace("'", "''")
                cuentas = dv.query(
                    entity='accounts',
                    filter_query=f"statecode eq 0 and name eq '{safe_nombre}'",
                    select_fields=['accountid', 'name', 'telephone1', 'emailaddress1'],
                    top=1
                )
                for cuenta in cuentas:
                    if cuenta['accountid'] not in ids_existentes:
                        comercializadoras_candidatas.append(cuenta)
                        ids_existentes.add(cuenta['accountid'])
            except:
                pass
        
        resultado = []
        for com in comercializadoras_candidatas:
            if not com.get('name'): continue
            
            nombre = com['name']
            es_relevante = any(n.lower() in nombre.lower() for n in COMERCIALIZADORAS_RELEVANTES)
            es_proveedor = com.get('accountcategorycode') == 1
            
            if es_relevante or es_proveedor:
                resultado.append(
                    ComercializadoraResponse(
                        id=com['accountid'],
                        nombre=nombre,
                        telefono=com.get('telephone1'),
                        email=com.get('emailaddress1'),
                        activa=True,
                        total_productos=0
                    )
                )
        
        resultado.sort(key=lambda x: x.nombre.lower())
        logger.info(f"✅ Filtradas {len(resultado)} comercializadoras relevantes")
        return resultado
        
    except Exception as e:
        logger.error(f"Error listando comercializadoras: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/comercializadoras")
async def crear_comercializadora(data: ComercializadoraCreate):
    try:
        dv = DataverseClient()
        safe_nombre = data.nombre.replace("'", "''")
        existente = dv.query(
            entity='accounts',
            filter_query=f"name eq '{safe_nombre}' and statecode eq 0",
            select_fields=['accountid'],
            top=1
        )
        
        if existente:
            raise HTTPException(400, f"Ya existe '{data.nombre}'")
        
        nueva = {
            'name': data.nombre,
            'telephone1': data.telefono,
            'emailaddress1': data.email,
            'statecode': 0 if data.activa else 1,
            'accountcategorycode': 1
        }
        
        resultado = dv.create(entity='accounts', data=nueva)
        logger.info(f"✅ Comercializadora creada: {data.nombre}")
        
        return JSONResponse(
            status_code=201,
            content={
                "mensaje": "Creada exitosamente",
                "id": resultado.get('id', '') if isinstance(resultado, dict) else str(resultado),
                "nombre": data.nombre
            }
        )
        
    except HTTPException: raise
    except Exception as e:
        logger.error(f"Error creando: {e}")
        raise HTTPException(500, detail=str(e))

# ═══════════════════════════════════════════════════════════════
# ENDPOINT: SUBIDA SIMPLIFICADA
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# 🚀 ENDPOINT DE SUBIDA (VERSIÓN QUIRÚRGICA)
# ═══════════════════════════════════════════════════════════════

@router.post("/productos/upload")
async def subir_productos(
    file: UploadFile = File(...),
    comercializadora_id: str = Form(...)
):
    logger.info(f"🚀 Iniciando carga inteligente (Multi-Pestaña) para: {file.filename}")
    
    try:
        content = await file.read()
        
        # 1. MOTOR INTELIGENTE (Lee KIT, ZEN, PLUS, etc.)
        resultado = await process_pricing_excel(content)
        
        if not resultado["success"]:
            raise HTTPException(400, f"Error leyendo Excel: {resultado.get('error')}")
            
        productos = resultado["productos"]
        pestañas = resultado.get("pestañas_procesadas", [])
        
        if not productos:
            raise HTTPException(400, "El archivo es válido pero no se encontraron productos. ¿Está vacío?")
            
        logger.info(f"📦 Detectados {len(productos)} productos en pestañas: {pestañas}")

        # 2. FIX DATAVERSE (Búsqueda de UOMs para evitar Error 400)
        dv = DataverseClient()
        try:
            # Buscamos unidades reales configuradas en tu entorno
            grupos = dv.query('uomschedules', top=1)
            unidades = dv.query('uoms', top=1)
            
            if grupos and unidades:
                uom_schedule = grupos[0]['uomscheduleid']
                uom_id = unidades[0]['uomid']
            else:
                # Fallback solo si la query devuelve vacío (raro)
                logger.warning("⚠️ Dataverse sin UOMs, intentando IDs estándar...")
                uom_schedule = '6a03d3b4-e911-4c52-b7fe-9f59a0d2f5db' 
                uom_id = 'e07e27be-ad31-4060-b6bf-8fc76f94728b'
        except Exception as e:
            logger.error(f"❌ Error crítico buscando UOMs: {e}")
            # No bloqueamos el proceso, intentamos seguir, pero logueamos el riesgo
            uom_schedule = '6a03d3b4-e911-4c52-b7fe-9f59a0d2f5db'
            uom_id = 'e07e27be-ad31-4060-b6bf-8fc76f94728b'

        # 3. GUARDADO MASIVO (Upsert)
        exitosos = 0
        errores = 0
        detalles_exitosos = []
        detalles_errores = []
        
        for i, p in enumerate(productos, start=1):
            try:
                # Payload preparado para Dataverse
                data = {
                    "name": p['nombre'],
                    "productnumber": p['codigo'],
                    "price": float(p['price']),
                    "description": f"Tarifa: {p['tarifa']} | Familia: {p['pestaña']}",
                    "statecode": 0,
                    "productstructure": 1,
                    "defaultuomscheduleid@odata.bind": f"/uomschedules({uom_schedule})",
                    "defaultuomid@odata.bind": f"/uoms({uom_id})",
                    "cr4ce_ComercializadoraRelacionada@odata.bind": f"/accounts({comercializadora_id})"
                }
                
                # Upsert: Si existe el código, actualiza. Si no, crea.
                safe_code = p['codigo'].replace("'", "''")
                existente = dv.query('products', f"productnumber eq '{safe_code}'", top=1)
                
                accion = "creado"
                if existente:
                    dv.update('products', existente[0]['productid'], data)
                    accion = "actualizado"
                else:
                    dv.create('products', data)
                
                exitosos += 1
                detalles_exitosos.append({
                    "fila": i,
                    "codigo": p['codigo'],
                    "nombre": p['nombre'],
                    "accion": accion
                })
                
            except Exception as e:
                errores += 1
                logger.error(f"❌ Error guardando {p['nombre']}: {e}")
                detalles_errores.append({
                    "fila": i,
                    "nombre": p['nombre'],
                    "error": str(e)
                })

        return {
            "mensaje": f"Proceso completado. Pestañas leídas: {', '.join(pestañas)}",
            "exitosos": exitosos,
            "errores": errores,
            "total_procesado": len(productos),
            "detalles_exitosos": detalles_exitosos,
            "detalles_errores": detalles_errores,
            "estadisticas": { # Mantenemos por compatibilidad si algo lo usa
                "total_detectado": len(productos),
                "subidos_ok": exitosos, 
                "fallidos": errores
            }
        }

    except Exception as e:
        logger.error(f"🔥 Error fatal en upload: {e}")
        raise HTTPException(500, str(e))

# ═══════════════════════════════════════════════════════════════
# ENDPOINT: LISTAR PRODUCTOS POR COMERCIALIZADORA
# ═══════════════════════════════════════════════════════════════

def limpiar_descripcion_visual(descripcion: str) -> str:
    if not descripcion: return ""
    return re.sub(r'#LINK#:[^#]+#\s*', '', descripcion).strip()

@router.get("/comercializadoras/{comercializadora_id}/productos")
async def listar_productos_comercializadora(comercializadora_id: str):
    """Lista productos filtrando por el ID oculto en descripción"""
    try:
        dv = DataverseClient()
        logger.info(f"📦 Obteniendo productos para {comercializadora_id}")
        
        productos = []
        try:
            # MÉTODO 1: Filtrar directamente en Dataverse (más eficiente)
            filtro_desc = f"contains(description, '{comercializadora_id}')"
            productos_filtrados = dv.query(
                entity='products',
                filter_query=filtro_desc,
                select_fields=['productid', 'name', 'productnumber', 'price', 'description', 'statecode'],
                top=2000
            )
            
            # Verificación adicional: comprobar patrón exacto #LINK#
            link_pattern = f"#LINK#:{comercializadora_id}#"
            productos = [p for p in productos_filtrados if p.get('description') and link_pattern in p.get('description', '')]
            
            logger.info(f"   📊 Filtro Dataverse: {len(productos_filtrados)} | Patrón #LINK# exacto: {len(productos)}")
            
            # Si el filtro estricto da 0 pero hay resultados del filtro general, usar esos
            if not productos and productos_filtrados:
                logger.warning(f"   ⚠️ Patrón #LINK# no coincide, usando filtro general")
                productos = productos_filtrados
                
        except Exception as e:
            logger.error(f"Error filtro descripción: {e}", exc_info=True)

        return {
            "comercializadora_id": comercializadora_id,
            "total": len(productos),
            "productos": [
                {
                    "id": p.get('productid'),
                    "nombre": p.get('name') or 'Producto Sin Nombre',
                    "codigo": p.get('productnumber', 'N/A'),
                    "precio": p.get('price', 0),
                    "descripcion": limpiar_descripcion_visual(p.get('description', '')),
                    "activo": p.get('statecode') == 0
                }
                for p in productos
            ]
        }
        
    except Exception as e:
        logger.error(f"Error listando productos: {e}", exc_info=True)
        raise HTTPException(500, str(e))

# ═══════════════════════════════════════════════════════════════
# ENDPOINT: CREACIÓN MANUAL DE PRODUCTOS
# ═══════════════════════════════════════════════════════════════

class ProductoManualCreate(BaseModel):
    nombre: str
    precio: float = 0.0
    tarifa: str
    comercializadora_id: str
    descripcion: Optional[str] = None

@router.post("/productos/manual")
async def crear_producto_manual(producto: ProductoManualCreate):
    """
    Endpoint para crear productos manualmente desde el Frontend.
    
    ✅ VENTAJAS:
    - Busca automáticamente los UOMs en Dataverse para evitar error 400
    - Construye el "Magic Link" de vinculación con la comercializadora
    - Validación robusta de datos
    - Manejo de duplicados
    """
    try:
        dv = DataverseClient()
        
        # 1️⃣ BÚSQUEDA AUTOMÁTICA DE UOMs (crítico para evitar error 400)
        logger.info("🔍 Buscando UOMs válidos en Dataverse...")
        uom_schedule_id = None
        uom_id = None
        
        try:
            grupos = dv.query('uomschedules', top=1)
            unidades = dv.query('uoms', top=1)
            
            if grupos and len(grupos) > 0:
                uom_schedule_id = grupos[0].get('uomscheduleid')
                logger.info(f"   ✅ UOM Schedule ID: {uom_schedule_id}")
            
            if unidades and len(unidades) > 0:
                uom_id = unidades[0].get('uomid')
                logger.info(f"   ✅ UOM ID: {uom_id}")
        
        except Exception as uom_error:
            logger.warning(f"⚠️ No se pudieron obtener UOMs: {uom_error}")
            # Continuamos sin UOMs - puede funcionar en algunos entornos
        
        # 2️⃣ CONSTRUCCIÓN DEL NOMBRE FINAL
        nombre_final = f"{producto.nombre} ({producto.tarifa})"
        
        # 3️⃣ GENERAR CÓDIGO ÚNICO
        timestamp = int(datetime.now().timestamp())
        codigo = f"MANUAL-{timestamp}"
        
        # 4️⃣ CONSTRUIR DESCRIPCIÓN CON MAGIC LINK
        desc_base = producto.descripcion or f"Producto creado manualmente - Tarifa {producto.tarifa}"
        descripcion = f"#LINK#:{producto.comercializadora_id}# {desc_base}"
        
        # 5️⃣ VERIFICAR DUPLICADOS
        safe_nombre = nombre_final.replace("'", "''")
        existente = dv.query(
            entity='products',
            filter_query=f"name eq '{safe_nombre}' and statecode eq 0",
            select_fields=['productid', 'name'],
            top=1
        )
        
        if existente:
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe un producto con el nombre '{nombre_final}'"
            )
        
        # 6️⃣ CONSTRUIR PAYLOAD COMPLETO
        payload = {
            'name': nombre_final,
            'productnumber': codigo,
            'description': descripcion,
            'price': producto.precio,
            'statecode': 0,
            'productstructure': 1  # Producto individual
        }
        
        # 7️⃣ AGREGAR UOMs SI ESTÁN DISPONIBLES
        if uom_schedule_id and uom_id:
            payload['defaultuomscheduleid@odata.bind'] = f"/uomschedules({uom_schedule_id})"
            payload['defaultuomid@odata.bind'] = f"/uoms({uom_id})"
            logger.info("   🔗 UOMs incluidos en el payload")
        else:
            logger.warning("   ⚠️ Creando producto sin UOMs (puede fallar en algunos entornos)")
        
        # 8️⃣ CREAR EN DATAVERSE
        logger.info(f"📦 Creando producto: {nombre_final}")
        resultado = dv.create(entity='products', data=payload)
        
        product_id = resultado.get('id', '') if isinstance(resultado, dict) else str(resultado)
        
        logger.info(f"✅ Producto creado exitosamente: {product_id}")
        
        return {
            "mensaje": "Producto creado exitosamente",
            "id": product_id,
            "nombre": nombre_final,
            "codigo": codigo,
            "tarifa": producto.tarifa,
            "precio": producto.precio,
            "uoms_incluidos": bool(uom_schedule_id and uom_id)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
            error_msg = e.response.text
        
        logger.error(f"❌ Error creando producto manual: {error_msg}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error al crear producto: {error_msg[:200]}"
        )

# ═══════════════════════════════════════════════════════════════
# ENDPOINT TEMPORAL: DEBUG CSV
# ═══════════════════════════════════════════════════════════════

@router.post("/productos/debug-csv")
async def debug_csv(file: UploadFile = File(...)):
    """Endpoint temporal para debuggear CSVs - muestra las primeras filas"""
    try:
        contenido = await file.read()
        
        # Leer CSV
        df = pd.read_csv(io.BytesIO(contenido), header=None, encoding='utf-8', on_bad_lines='skip')
        
        # Mostrar info básica
        info = {
            "total_filas": len(df),
            "total_columnas": len(df.columns),
            "primeras_20_filas": []
        }
        
        # Mostrar las primeras 20 filas
        for idx, row in df.head(20).iterrows():
            fila_texto = " | ".join([str(x) if pd.notna(x) else "VACÍO" for x in row])
            info["primeras_20_filas"].append({
                "fila": idx,
                "contenido": fila_texto,
                "columnas": [str(x) if pd.notna(x) else None for x in row]
            })
        
        return info
        
    except Exception as e:
        logger.error(f"Error debug CSV: {e}", exc_info=True)
        raise HTTPException(500, str(e))
