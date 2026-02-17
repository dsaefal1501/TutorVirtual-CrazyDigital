from app.db.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE mensajes_chat ADD COLUMN usuario_id INTEGER REFERENCES usuarios(id);"))
        conn.commit()
        print("Migración completada: usuario_id agregado.")
    except Exception as e:
        print(f"Error: {e}")
