from app.db.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    try:
        # Add column with default TRUE for existing users (safety first, or FALSE if we assume they are old)
        # Let's default to FALSE for EXISTING users to not annoy them, but TRUE for new ones (handled by logic)
        # Actually model default is True. Let's set False for existing to avoid locking out admin or others unexpectedly if logic is strict.
        # But wait, logic only applies to 'student'.
        conn.execute(text("ALTER TABLE usuarios ADD COLUMN must_change_password BOOLEAN DEFAULT TRUE;"))
        
        # Optional: Set to False for specific existing users if needed, but default True is safer for security.
        # If I want to allow current users to skip:
        # conn.execute(text("UPDATE usuarios SET must_change_password = FALSE;")) 
        
        conn.commit()
        print("Migración completada: must_change_password agregado.")
    except Exception as e:
        print(f"Error: {e}")
