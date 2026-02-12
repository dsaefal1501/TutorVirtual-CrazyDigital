"""
Servicio de Fragmentación Token-Based (Chunking)
Implementa fragmentación de tamaño fijo con overlap usando tiktoken.
Parámetros óptimos: 450 tokens por chunk, 70 tokens de overlap (~15%).
"""
import re
from typing import List, Dict, Any, Optional

try:
    import tiktoken
    # Tokenizador compatible con text-embedding-3-small
    TOKENIZER = tiktoken.get_encoding("cl100k_base")
except ImportError:
    TOKENIZER = None
    print("ADVERTENCIA: tiktoken no instalado. Usando estimación por caracteres.")

# ============================================================================
# Constantes de Configuración
# ============================================================================

CHUNK_SIZE = 450       # Tokens por fragmento (rango óptimo: 400-500)
CHUNK_OVERLAP = 70     # Tokens de solapamiento (~15% del chunk)

# ============================================================================
# Funciones de Tokenización
# ============================================================================

def contar_tokens(texto: str) -> int:
    """Cuenta tokens usando tiktoken o estimación fallback."""
    if TOKENIZER:
        return len(TOKENIZER.encode(texto))
    # Fallback: ~1 token = 4 caracteres en español
    return len(texto) // 4


def _dividir_en_sentencias(texto: str) -> List[str]:
    """Divide el texto en sentencias respetando puntuación."""
    # Patrón: divide en punto seguido de espacio/newline, ?, !, o doble newline
    sentencias = re.split(r'(?<=[.!?])\s+|\n\n+', texto)
    return [s.strip() for s in sentencias if s.strip()]


# ============================================================================
# Fragmentación Token-Based con Overlap
# ============================================================================

def fragmentar_texto(
    texto: str, 
    chunk_size: int = CHUNK_SIZE, 
    overlap: int = CHUNK_OVERLAP
) -> List[str]:
    """
    Fragmenta el texto en chunks de tamaño fijo (en tokens) con overlap.
    
    Algoritmo:
    1. Divide el texto en sentencias
    2. Agrupa sentencias hasta alcanzar chunk_size tokens
    3. Al cerrar un chunk, retrocede overlap tokens para el siguiente
    4. Nunca corta a mitad de sentencia
    
    Args:
        texto: Texto a fragmentar
        chunk_size: Tamaño máximo por fragmento en tokens (default: 450)
        overlap: Solapamiento entre fragmentos en tokens (default: 70)
    
    Returns:
        Lista de fragmentos de texto
    """
    if not texto or not texto.strip():
        return []
    
    texto = texto.strip()
    total_tokens = contar_tokens(texto)
    
    # Si el texto cabe en un solo chunk, devolverlo tal cual
    if total_tokens <= chunk_size:
        return [texto]
    
    sentencias = _dividir_en_sentencias(texto)
    
    if not sentencias:
        return [texto]
    
    fragmentos = []
    chunk_actual = []
    tokens_chunk_actual = 0
    idx_sentencia = 0
    
    while idx_sentencia < len(sentencias):
        sentencia = sentencias[idx_sentencia]
        tokens_sentencia = contar_tokens(sentencia)
        
        # Si una sola sentencia supera el chunk_size, forzar su inclusión
        if tokens_sentencia > chunk_size and not chunk_actual:
            fragmentos.append(sentencia)
            idx_sentencia += 1
            continue
        
        # Si la sentencia cabe en el chunk actual
        if tokens_chunk_actual + tokens_sentencia <= chunk_size:
            chunk_actual.append(sentencia)
            tokens_chunk_actual += tokens_sentencia
            idx_sentencia += 1
        else:
            # Cerrar chunk actual
            if chunk_actual:
                fragmentos.append(" ".join(chunk_actual))
            
            # Calcular overlap: retroceder sentencias hasta cubrir ~overlap tokens
            tokens_overlap = 0
            inicio_overlap = len(chunk_actual)
            
            for j in range(len(chunk_actual) - 1, -1, -1):
                tokens_overlap += contar_tokens(chunk_actual[j])
                if tokens_overlap >= overlap:
                    inicio_overlap = j
                    break
            
            # Iniciar nuevo chunk con las sentencias de overlap
            chunk_actual = chunk_actual[inicio_overlap:]
            tokens_chunk_actual = sum(contar_tokens(s) for s in chunk_actual)
    
    # Agregar el último chunk si tiene contenido
    if chunk_actual:
        ultimo = " ".join(chunk_actual)
        # Solo agregar si no es un duplicado del último fragmento
        if not fragmentos or ultimo != fragmentos[-1]:
            fragmentos.append(ultimo)
    
    return fragmentos


# ============================================================================
# Detección de Tipo de Contenido
# ============================================================================

def detectar_tipo_contenido(texto: str) -> str:
    """
    Clasifica un fragmento como 'texto' (teoría) o 'codigo' (Python).
    Usa heurísticas basadas en patrones comunes de código Python.
    """
    lineas = texto.split('\n')
    indicadores_codigo = 0
    total_lineas = len(lineas)
    
    if total_lineas == 0:
        return "texto"
    
    patrones_codigo = [
        r'^\s*(def |class |import |from .+ import)',  # Declaraciones
        r'^\s*(if |elif |else:|for |while |try:|except|finally:)',  # Control
        r'^\s*(return |yield |raise |with )',  # Keywords
        r'^\s*#\s',  # Comentarios Python
        r'>>>\s',  # REPL Python
        r'^\s*(print\(|input\(|len\(|range\()',  # Funciones comunes
        r'[=!<>]=|[+\-*/]=',  # Operadores de asignación
        r'^\s{4,}\S',  # Indentación de 4+ espacios
        r'\[.*\]|\{.*\}',  # Listas/diccionarios literales
    ]
    
    for linea in lineas:
        for patron in patrones_codigo:
            if re.search(patron, linea):
                indicadores_codigo += 1
                break
    
    # Si más del 40% de las líneas tienen patrones de código
    ratio = indicadores_codigo / total_lineas if total_lineas > 0 else 0
    return "codigo" if ratio > 0.4 else "texto"


# ============================================================================
# Enriquecimiento con Metadatos
# ============================================================================

def enriquecer_fragmentos(
    fragmentos: List[str],
    metadata_base: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Enriquece cada fragmento con metadatos descriptivos.
    
    Args:
        fragmentos: Lista de textos fragmentados
        metadata_base: Metadatos comunes (fuente, página, capítulo, etc.)
    
    Returns:
        Lista de diccionarios con 'contenido', 'tipo', 'tokens', 'metadata'
    """
    resultado = []
    
    for idx, fragmento in enumerate(fragmentos):
        tipo = detectar_tipo_contenido(fragmento)
        tokens = contar_tokens(fragmento)
        
        meta = {
            **metadata_base,
            "chunk_index": idx + 1,
            "total_chunks": len(fragmentos),
            "tipo_contenido": tipo,
            "tokens": tokens,
        }
        
        resultado.append({
            "contenido": fragmento,
            "tipo": tipo,
            "tokens": tokens,
            "orden": idx + 1,
            "metadata": meta,
        })
    
    return resultado


# ============================================================================
# Función Principal de Procesamiento
# ============================================================================

def procesar_texto_tema(
    texto: str,
    nombre_tema: str,
    nivel: int,
    orden: int,
    pagina_inicio: int,
    parent_nombre: str = "",
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> List[Dict[str, Any]]:
    """
    Pipeline completo: fragmentar + detectar tipo + enriquecer metadatos.
    
    Args:
        texto: Texto completo del tema
        nombre_tema: Nombre del tema/sección
        nivel: Nivel jerárquico (1=capítulo, 2=sección)
        orden: Orden dentro de su nivel
        pagina_inicio: Página de inicio en el libro
        parent_nombre: Nombre del capítulo padre
        chunk_size: Tokens por fragmento
        overlap: Tokens de overlap
    
    Returns:
        Lista de bloques procesados listos para insertar en BaseConocimiento
    """
    if not texto or not texto.strip():
        return []
    
    # 1. Fragmentar
    fragmentos = fragmentar_texto(texto, chunk_size, overlap)
    
    # 2. Construir posición legible
    if parent_nombre:
        posicion = f"{parent_nombre} > {nombre_tema} (nivel {nivel}, orden {orden})"
    else:
        posicion = f"{nombre_tema} (nivel {nivel}, orden {orden})"
    
    # 3. Enriquecer con metadatos
    metadata_base = {
        "titulo": nombre_tema,
        "nivel": nivel,
        "orden": orden,
        "parent_nombre": parent_nombre,
        "posicion": posicion,
        "pagina_inicio": pagina_inicio,
        "origen": "chunking_token_based_v1",
    }
    
    bloques = enriquecer_fragmentos(fragmentos, metadata_base)
    
    return bloques
