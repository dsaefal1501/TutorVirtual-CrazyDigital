
import psycopg2

try:
    conn = psycopg2.connect("postgresql://postgres:root@127.0.0.1:5433/pruebatutorvirtual")
    cur = conn.cursor()
    
    print("Intentando insertar registro con chunk_anterior_id...")
    # Solo intentamos preparar el statement, no ejecutarlo realmente si falta datos FK
    # Pero verificamos si la columna es reconocida
    cur.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'base_conocimiento' AND column_name = 'chunk_anterior_id';
    """)
    res = cur.fetchone()
    if res:
        print(f"✅ Columna encontrada: {res[0]}")
    else:
        print("❌ Columna NO encontrada en information_schema")
        
    conn.close()

except Exception as e:
    print(f"Error: {e}")
