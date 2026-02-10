from app.db.database import engine
from app.models.modelos import Base, BaseConocimiento, MensajeChat
from sqlalchemy import text

def reset_tables():
    print("Conectando a la base de datos...")
    with engine.connect() as conn:
        try:
            print("Eliminando tabla 'base_conocimiento'...")
            conn.execute(text("DROP TABLE IF EXISTS base_conocimiento CASCADE"))
            
            print("Eliminando tabla 'mensajes_chat'...")
            conn.execute(text("DROP TABLE IF EXISTS mensajes_chat CASCADE"))
            
            conn.commit()
            print("Tablas eliminadas correctamente.")
        except Exception as e:
            print(f"Error al eliminar tablas: {e}")

    print("Recreando tablas con la nueva definición (Vector 1024)...")
    # Esto creará solo las tablas que faltan (las que acabamos de borrar)
    Base.metadata.create_all(bind=engine)
    print("Tablas recreadas correctamente.")

if __name__ == "__main__":
    reset_tables()
