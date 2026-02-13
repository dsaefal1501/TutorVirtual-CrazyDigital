import psycopg2
from psycopg2 import sql

# Datos de conexión
DB_HOST = "127.0.0.1"
DB_PORT = "5433"
DB_NAME = "pruebatutorvirtual"
DB_USER = "postgres"
DB_PASS = "root"

def check_and_fix():
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        conn.autocommit = True
        cur = conn.cursor()
        
        # 1. Verificar columnas actuales
        print("🔍 Verificando columnas en 'base_conocimiento'...")
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'base_conocimiento';
        """)
        cols = [row[0] for row in cur.fetchall()]
        print(f"   Columnas encontradas: {cols}")
        
        if "chunk_anterior_id" not in cols:
            print("❌ Faltan columnas nuevas. El schema NO se actualizó.")
            
            # 2. Forzar actualización
            print("\n🚀 Forzando ejecución de schema_final.sql...")
            
            # Leer SQL
            with open("schema_final.sql", "r", encoding="utf-8") as f:
                sql_content = f.read()
            
            # Forzar DROP y recrear
            try:
                cur.execute("DROP SCHEMA public CASCADE;")
                cur.execute("CREATE SCHEMA public;")
                cur.execute("GRANT ALL ON SCHEMA public TO postgres;")
                cur.execute("GRANT ALL ON SCHEMA public TO public;")
                print("   ✓ Schema public recreado limpio.")
                
                cur.execute(sql_content)
                print("   ✓ schema_final.sql ejecutado EXITOSAMENTE.")
                
            except Exception as e:
                print(f"   🔥 Error ejecutando SQL: {e}")
        else:
            print("✅ Las columnas existen. Todo parece correcto.")

        # Verificar de nuevo
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'base_conocimiento';
        """)
        cols_final = [row[0] for row in cur.fetchall()]
        if "chunk_anterior_id" in cols_final:
             print("\n🎉 VERIFICACIÓN FINAL: EXITO. Las columnas están presentes.")
        else:
             print("\n💀 VERIFICACIÓN FINAL: FALLO. Siguen faltando columnas.")

        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"Error de conexión o ejecución: {e}")

if __name__ == "__main__":
    check_and_fix()
