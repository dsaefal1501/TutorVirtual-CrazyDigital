"""
Servicio de Evaluaciones Dinámicas (Assessment Service)
Genera tests desde el contenido vectorizado (RAG) y corrige respuestas abiertas (LLM-as-a-Judge).
"""
import json
import os
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select

from mistralai import Mistral
from app.models.modelos import BaseConocimiento, Temario, Assessment, TestScore
from app.crud.embedding_service import generar_embedding

# Cliente Mistral (para generación de tests y corrección)
api_key = os.getenv("MISTRAL_API_KEY")
client = Mistral(api_key=api_key) if api_key else None


# ============================================================================
# 1. GENERACIÓN DINÁMICA DE EVALUACIONES
# ============================================================================

def generar_evaluacion(
    db: Session, 
    temario_id: int, 
    num_preguntas: int = 5,
    temperatura: float = 0.7
) -> Dict[str, Any]:
    """
    Genera una evaluación dinámica basada en el contenido del temario indexado.
    
    Pipeline:
    1. Recupera fragmentos del temario desde la base vectorial
    2. Construye meta-prompt para generar preguntas diversificadas
    3. Fuerza salida JSON estructurada
    4. Persiste en tabla Assessment
    
    Args:
        db: Sesión de base de datos
        temario_id: ID del temario sobre el que generar la evaluación
        num_preguntas: Número de preguntas a generar
        temperatura: Controla variabilidad (0.0=determinista, 1.0=creativo)
    
    Returns:
        Diccionario con la evaluación generada y su ID en la DB
    """
    # 1. Obtener info del tema
    tema = db.query(Temario).filter(Temario.id == temario_id).first()
    if not tema:
        return {"error": f"Temario con id={temario_id} no encontrado"}
    
    # 2. Recuperar fragmentos del tema (contenido del libro)
    bloques = db.query(BaseConocimiento).filter(
        BaseConocimiento.temario_id == temario_id
    ).order_by(BaseConocimiento.orden_aparicion.asc()).all()
    
    if not bloques:
        return {"error": f"No hay contenido indexado para el temario '{tema.nombre}'"}
    
    # Concatenar contenido para contexto
    contenido_completo = "\n\n".join([
        f"[Bloque {b.orden_aparicion} - Tipo: {b.tipo_contenido}]\n{b.contenido}" 
        for b in bloques
    ])
    
    # 3. Meta-prompt para generación de evaluaciones
    prompt_generacion = f"""
    ERES UN GENERADOR DE EVALUACIONES ACADÉMICAS EXPERTO.
    
    CONTEXTO DEL LIBRO (usa EXCLUSIVAMENTE este contenido para formular preguntas):
    ---
    {contenido_completo[:8000]}
    ---
    
    TEMA: {tema.nombre}
    
    INSTRUCCIONES:
    1. Genera exactamente {num_preguntas} preguntas sobre el contenido anterior.
    2. Tipos de preguntas a incluir:
       - Al menos 2 de opción múltiple (4 opciones, una correcta)
       - Al menos 1 de verdadero/falso
       - Al menos 1 pregunta abierta (respuesta corta)
    3. Cada pregunta debe tener:
       - enunciado: El texto de la pregunta
       - tipo: "opcion_multiple", "verdadero_falso", o "abierta"
       - opciones: Array de opciones (solo para opción múltiple y V/F)
       - respuesta_correcta: Índice (0-based) para opción múltiple/V/F, o texto para abierta
       - justificacion: Explicación de por qué es correcta (cita del libro)
       - dificultad: 1 (fácil), 2 (media), 3 (difícil)
    
    FORMATO JSON ESTRICTO:
    {{
        "titulo": "Evaluación sobre [tema]",
        "preguntas": [
            {{
                "enunciado": "...",
                "tipo": "opcion_multiple",
                "opciones": ["A) ...", "B) ...", "C) ...", "D) ..."],
                "respuesta_correcta": 0,
                "justificacion": "...",
                "dificultad": 1
            }},
            {{
                "enunciado": "...",
                "tipo": "verdadero_falso",
                "opciones": ["Verdadero", "Falso"],
                "respuesta_correcta": 0,
                "justificacion": "...",
                "dificultad": 1
            }},
            {{
                "enunciado": "...",
                "tipo": "abierta",
                "opciones": [],
                "respuesta_correcta": "La respuesta esperada...",
                "justificacion": "...",
                "dificultad": 2
            }}
        ]
    }}
    """
    
    if not client:
        return {"error": "No hay cliente Mistral configurado"}
    
    try:
        response = client.chat.complete(
            model="mistral-large-latest",
            messages=[
                {"role": "system", "content": prompt_generacion},
                {"role": "user", "content": f"Genera {num_preguntas} preguntas sobre: {tema.nombre}"}
            ],
            response_format={"type": "json_object"},
            temperature=temperatura
        )
        
        evaluacion_json = json.loads(response.choices[0].message.content)
        
        # 4. Persistir en tabla Assessment
        preguntas = evaluacion_json.get("preguntas", [])
        titulo = evaluacion_json.get("titulo", f"Evaluación: {tema.nombre}")
        
        nueva_evaluacion = Assessment(
            temario_id=temario_id,
            titulo=titulo,
            topic_metadata=tema.nombre,
            total_preguntas=len(preguntas),
            generated_json_payload=evaluacion_json,
            temperatura=temperatura,
        )
        db.add(nueva_evaluacion)
        db.commit()
        db.refresh(nueva_evaluacion)
        
        return {
            "assessment_id": nueva_evaluacion.id,
            "titulo": titulo,
            "total_preguntas": len(preguntas),
            "preguntas": preguntas,
        }
        
    except Exception as e:
        print(f"Error generando evaluación: {e}")
        return {"error": str(e)}


# ============================================================================
# 2. CORRECCIÓN SEMÁNTICA (LLM-as-a-Judge)
# ============================================================================

def corregir_respuesta_abierta(
    db: Session,
    assessment_id: int,
    pregunta_idx: int,
    respuesta_alumno: str,
    usuario_id: int,
) -> Dict[str, Any]:
    """
    Corrige una respuesta abierta usando el paradigma LLM-as-a-Judge.
    
    Compara semánticamente la respuesta del alumno contra la respuesta 
    esperada (golden answer) extraída del libro.
    
    Args:
        db: Sesión de base de datos
        assessment_id: ID de la evaluación
        pregunta_idx: Índice de la pregunta dentro del assessment
        respuesta_alumno: Texto de la respuesta del alumno
        usuario_id: ID del usuario
    
    Returns:
        Score (0-100) + feedback textual
    """
    # Obtener la evaluación
    assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not assessment:
        return {"error": "Evaluación no encontrada"}
    
    preguntas = assessment.generated_json_payload.get("preguntas", [])
    if pregunta_idx >= len(preguntas):
        return {"error": f"Pregunta {pregunta_idx} no existe en la evaluación"}
    
    pregunta = preguntas[pregunta_idx]
    enunciado = pregunta["enunciado"]
    respuesta_correcta = pregunta["respuesta_correcta"]
    justificacion = pregunta.get("justificacion", "")
    
    # Prompt de corrección LLM-as-a-Judge
    prompt_juez = f"""
    ERES UN EVALUADOR ACADÉMICO EXPERTO. Tu tarea es calificar la respuesta de un alumno.
    
    PREGUNTA: {enunciado}
    
    RESPUESTA CORRECTA (Golden Answer): {respuesta_correcta}
    JUSTIFICACIÓN BIBLIOGRÁFICA: {justificacion}
    
    RESPUESTA DEL ALUMNO: {respuesta_alumno}
    
    INSTRUCCIONES DE CALIFICACIÓN:
    1. Evalúa si la respuesta del alumno aborda los conceptos clave requeridos.
    2. Acepta parafraseo, sinónimos y diferentes formas de expresar la misma idea.
    3. NO penalices por diferencias puramente sintácticas o de vocabulario.
    4. SÍ penaliza errores conceptuales o información incorrecta.
    
    FORMATO JSON:
    {{
        "score": <número de 0 a 100>,
        "nivel": "<insuficiente|basico|competente|excelente>",
        "feedback": "<retroalimentación constructiva para el alumno>",
        "conceptos_correctos": ["<lista de conceptos bien abordados>"],
        "conceptos_faltantes": ["<lista de conceptos que debió mencionar>"]
    }}
    """
    
    if not client:
        return {"error": "No hay cliente Mistral configurado"}
    
    try:
        response = client.chat.complete(
            model="mistral-large-latest",
            messages=[
                {"role": "system", "content": prompt_juez},
                {"role": "user", "content": "Califica la respuesta del alumno."}
            ],
            response_format={"type": "json_object"},
            temperature=0.1  # Baja temperatura para corrección determinista
        )
        
        resultado = json.loads(response.choices[0].message.content)
        
        # Guardar calificación en TestScore
        score_valor = resultado.get("score", 0)
        feedback = resultado.get("feedback", "")
        
        nuevo_score = TestScore(
            assessment_id=assessment_id,
            usuario_id=usuario_id,
            score=score_valor,
            respuestas_alumno={
                "pregunta_idx": pregunta_idx,
                "respuesta": respuesta_alumno
            },
            ai_feedback_log=json.dumps(resultado, ensure_ascii=False),
        )
        db.add(nuevo_score)
        db.commit()
        db.refresh(nuevo_score)
        
        return {
            "score_id": nuevo_score.id,
            "score": score_valor,
            "nivel": resultado.get("nivel", ""),
            "feedback": feedback,
            "conceptos_correctos": resultado.get("conceptos_correctos", []),
            "conceptos_faltantes": resultado.get("conceptos_faltantes", []),
        }
        
    except Exception as e:
        print(f"Error en corrección semántica: {e}")
        return {"error": str(e)}


# ============================================================================
# 3. CORRECCIÓN DE OPCIÓN MÚLTIPLE (Determinista)
# ============================================================================

def corregir_opcion_multiple(
    db: Session,
    assessment_id: int,
    respuestas: Dict[int, int],
    usuario_id: int,
) -> Dict[str, Any]:
    """
    Corrige respuestas de opción múltiple/verdadero-falso de forma determinista.
    
    Args:
        db: Sesión de base de datos
        assessment_id: ID de la evaluación
        respuestas: Dict {pregunta_idx: indice_respuesta}
        usuario_id: ID del usuario
    
    Returns:
        Score total + detalle por pregunta
    """
    assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
    if not assessment:
        return {"error": "Evaluación no encontrada"}
    
    preguntas = assessment.generated_json_payload.get("preguntas", [])
    correctas = 0
    total = 0
    detalle = []
    
    for idx, resp_alumno in respuestas.items():
        idx = int(idx)
        if idx >= len(preguntas):
            continue
        
        pregunta = preguntas[idx]
        if pregunta["tipo"] == "abierta":
            continue  # Las abiertas se corrigen con corregir_respuesta_abierta
        
        total += 1
        es_correcta = resp_alumno == pregunta["respuesta_correcta"]
        if es_correcta:
            correctas += 1
        
        detalle.append({
            "pregunta_idx": idx,
            "correcta": es_correcta,
            "respuesta_alumno": resp_alumno,
            "respuesta_correcta": pregunta["respuesta_correcta"],
            "justificacion": pregunta.get("justificacion", ""),
        })
    
    score = (correctas / total * 100) if total > 0 else 0
    
    # Persistir
    nuevo_score = TestScore(
        assessment_id=assessment_id,
        usuario_id=usuario_id,
        score=score,
        respuestas_alumno={"respuestas": respuestas, "detalle": detalle},
        ai_feedback_log=f"Correctas: {correctas}/{total}",
    )
    db.add(nuevo_score)
    db.commit()
    db.refresh(nuevo_score)
    
    return {
        "score_id": nuevo_score.id,
        "score": score,
        "correctas": correctas,
        "total": total,
        "detalle": detalle,
    }
