from app.db.database import SessionLocal
from app.models.modelos import Usuario, Licencia
from datetime import datetime
from sqlalchemy.exc import IntegrityError

def crear_usuario_pruebas():
    db = SessionLocal()
    try:
        print("--- Iniciando creación de datos de prueba ---")
        
        # 1. Crear o Buscar Licencia
        licencia = db.query(Licencia).filter(Licencia.cliente == "Colegio Demo").first()
        if not licencia:
            print("Creando licencia 'Colegio Demo'...")
            licencia = Licencia(
                cliente="Colegio Demo",
                max_alumnos=100,
                fecha_inicio=datetime.now(),
                fecha_fin=datetime.now()
            )
            db.add(licencia)
            db.commit()
            db.refresh(licencia)
            print(f"✅ Licencia creada (ID: {licencia.id})")
        else:
            print(f"ℹ️ Licencia ya existe (ID: {licencia.id})")

        # 2. Crear o Buscar Usuario
        usuario = db.query(Usuario).filter(Usuario.email == "alumno@prueba.com").first()
        if not usuario:
            print("Creando usuario 'alumno@prueba.com'...")
            usuario = Usuario(
                nombre="Juan Perez",
                email="alumno@prueba.com",
                password_hash="hashed_ref",
                rol="alumno",
                licencia_id=licencia.id # Usamos el ID de la licencia recuperada/creada
            )
            db.add(usuario)
            db.commit()
            db.refresh(usuario)
            print(f"✅ Usuario creado (ID: {usuario.id})")
        else:
            print(f"ℹ️ Usuario ya existe (ID: {usuario.id})")

    except Exception as e:
        print(f"❌ Error Fatal: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    crear_usuario_pruebas()
