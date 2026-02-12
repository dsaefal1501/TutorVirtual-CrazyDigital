"""
Script de migración: Vector(1024) → Vector(1536)
Ejecutar UNA VEZ para migrar de Mistral embeddings a OpenAI text-embedding-3-small.

Este script:
1. Altera las columnas vector de 1024 → 1536 dimensiones
2. Limpia embeddings viejos (incompatibles)
3. Crea las nuevas tablas LMS si no existen
"""
import sys
import os

# Añadir el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from app.db.database import engine
from app.models.modelos import Base

def migrar():
    print("=" * 60)
    print("MIGRACIÓN: Vector(1024) → Vector(1536)")
    print("OpenAI text-embedding-3-small")
    print("=" * 60)
    
    with engine.connect() as conn:
        # 1. Limpiar embedding_cache (datos incompatibles)
        print("\n[1/4] Limpiando embedding_cache...")
        conn.execute(text("DELETE FROM embedding_cache"))
        conn.commit()
        print("  → embedding_cache vaciada")
        
        # 2. Alterar columna en base_conocimiento
        print("\n[2/4] Alterando base_conocimiento.embedding → vector(1536)...")
        conn.execute(text("UPDATE base_conocimiento SET embedding = NULL"))
        conn.execute(text("ALTER TABLE base_conocimiento ALTER COLUMN embedding TYPE vector(1536)"))
        conn.commit()
        print("  → base_conocimiento.embedding actualizado")
        
        # 3. Alterar columna en mensajes_chat
        print("\n[3/4] Alterando mensajes_chat.embedding → vector(1536)...")
        conn.execute(text("UPDATE mensajes_chat SET embedding = NULL"))
        conn.execute(text("ALTER TABLE mensajes_chat ALTER COLUMN embedding TYPE vector(1536)"))
        conn.commit()
        print("  → mensajes_chat.embedding actualizado")
        
        # 4. Crear tablas nuevas (enrollments, assessments, test_scores, learning_events)
        print("\n[4/4] Creando tablas LMS nuevas...")
        Base.metadata.create_all(bind=engine)
        print("  → Tablas nuevas creadas (si no existían)")
    
    print("\n" + "=" * 60)
    print("MIGRACIÓN COMPLETADA")
    print("Ahora debes re-subir el PDF con /upload/syllabus")
    print("para regenerar los embeddings con OpenAI.")
    print("=" * 60)

if __name__ == "__main__":
    migrar()
