import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def fix_trigger():
    global DATABASE_URL
    # Fix for SQLAlchemy format
    if DATABASE_URL and DATABASE_URL.startswith("postgresql+psycopg2://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")

    print(f"Conectando a {DATABASE_URL}...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        print("1. Eliminando trigger conflictivo...")
        cur.execute("DROP TRIGGER IF EXISTS tsvectorupdate ON base_conocimiento;")
        
        print("2. Saltando eliminación de función ambigua (es del sistema)...")
        # cur.execute("DROP FUNCTION IF EXISTS tsvector_update_trigger();")
        
        print("3. Creando nueva función única 'fn_sync_busqueda_texto'...")
        cur.execute("""
        CREATE OR REPLACE FUNCTION fn_sync_busqueda_texto()
        RETURNS TRIGGER AS $$
        BEGIN
          NEW.busqueda_texto := setweight(to_tsvector('spanish', unaccent(COALESCE(NEW.contenido, ''))), 'A');
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """)
        
        print("4. Recreando trigger...")
        cur.execute("""
        CREATE TRIGGER tsvectorupdate BEFORE INSERT OR UPDATE
        ON base_conocimiento FOR EACH ROW EXECUTE FUNCTION fn_sync_busqueda_texto();
        """)
        
        conn.commit()
        print("✅ Trigger reparado exitosamente.")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    fix_trigger()
