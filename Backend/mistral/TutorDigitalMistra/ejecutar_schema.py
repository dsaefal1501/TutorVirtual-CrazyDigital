"""
Script para ejecutar el schema directamente con psycopg2
"""
import psycopg2
from psycopg2 import sql

# Leer connection string
conn_str = "postgresql://postgres:root@127.0.0.1:5433/pruebatutorvirtual"

print("Conectando a la base de datos...")
conn = psycopg2.connect(conn_str)
conn.autocommit = True
cur = conn.cursor()

print("Borrando schema actual...")
try:
    cur.execute("DROP SCHEMA public CASCADE;")
    cur.execute("CREATE SCHEMA public;")
    print("✓ Schema limpiado")
except Exception as e:
    print(f"⚠️ Error limpiando schema: {e}")

print("\\nEjecutando schema_final.sql...")
with open("schema_final.sql", "r", encoding="utf-8") as f:
    schema_sql = f.read()
    
try:
    cur.execute(schema_sql)
    print("✓ Schema ejecutado correctamente")
except Exception as e:
    print(f"✗ Error:', {e}")
finally:
    cur.close()
    conn.close()

print("\\n✓ Migración completada")
