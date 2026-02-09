import os
import time
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.models.modelos import Temario, BaseConocimiento
from mistralai import Mistral

# Configuración
api_key = os.getenv("MISTRAL_API_KEY")
client = Mistral(api_key=api_key)

def get_embedding(texto):
    """Genera embedding usando Mistral (con reintentos simples)"""
    try:
        resp = client.embeddings.create(
            model="mistral-embed",
            inputs=[texto]
        )
        return resp.data[0].embedding
    except Exception as e:
        print(f"Error generando embedding: {e}")
        return None

def poblar_base_conocimiento():
    db = SessionLocal()
    try:
        print("--- Iniciando Poblado de Base de Conocimiento ---")
        
        # 1. Obtener todos los temas que tengan descripción
        temas = db.query(Temario).filter(Temario.descripcion != None).all()
        print(f"Encontrados {len(temas)} temas con descripción.")

        count = 0
        for tema in temas:
            # Verificar si ya tiene conocimiento asociado (para no duplicar)
            existe = db.query(BaseConocimiento).filter(BaseConocimiento.temario_id == tema.id).first()
            if existe:
                print(f"Saltando tema ID {tema.id} ({tema.nombre}) - Ya tiene conocimiento.")
                continue

            print(f"Procesando tema ID {tema.id}: {tema.nombre}...")
            
            # El contenido será la concatenación del nombre y la descripción
            contenido_texto = f"Tema: {tema.nombre}.\nDescripción: {tema.descripcion}"
            
            # Generar Vector
            vector = get_embedding(contenido_texto)
            
            if vector:
                nuevo_conocimiento = BaseConocimiento(
                    temario_id=tema.id,
                    contenido=contenido_texto,
                    embedding=vector,
                    metadata_info={"origen": "migracion_temario"}
                )
                db.add(nuevo_conocimiento)
                count += 1
                
                # Guardar cada 10 para no perder progreso
                if count % 10 == 0:
                    db.commit()
                    print(f"--- Guardados {count} registros ---")
            
            # Pequeña pausa para no saturar la API
            time.sleep(0.5)

        db.commit()
        print(f"--- Finalizado. Se insertaron {count} nuevos registros en BaseConocimiento ---")

    except Exception as e:
        print(f"Error fatal: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    poblar_base_conocimiento()
