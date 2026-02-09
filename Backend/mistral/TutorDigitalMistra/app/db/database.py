from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

# 1. Cargar variables de entorno desde el archivo .env
load_dotenv()

# 2. Obtener la URL de la base de datos
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("No se ha configurado la variable DATABASE_URL en el archivo .env")

# 3. Crear el motor de la base de datos (Engine)
# El engine es el punto de entrada principal a la base de datos.
# Gestiona el pool de conexiones.
engine = create_engine(DATABASE_URL)

# 4. Crear la fábrica de sesiones (SessionLocal)
# Cada vez que necesitemos interactuar con la DB, pediremos una sesión a esta fábrica.
# autocommit=False: Para tener control manual de cuándo guardar los cambios.
# autoflush=False: Para evitar que se envíen datos a la DB antes de tiempo.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 5. Dependencia para obtener la sesión de base de datos (get_db)
# Esta función se usará en los endpoints de FastAPI.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
