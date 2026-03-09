import sys
import os

# Add current directory to path to allow importing src
sys.path.append(os.getcwd())
print(f"Current working directory: {os.getcwd()}")
print(f"System path: {sys.path}")

from sqlalchemy import create_engine, text, inspect
from src.config import Config

def add_logo_column():
    """Add logo column to club table"""
    
    # Get database URL from config
    database_url = Config.get_database_uri()
    if not database_url:
        print("Error: DATABASE_URL not found in environment")
        return False
        
    print(f"Connecting to database...")
    engine = create_engine(database_url)
    
    try:
        inspector = inspect(engine)
        # Check if table exists first
        if not inspector.has_table('club'):
            print("Error: 'club' table not found.")
            return False

        columns = [c['name'] for c in inspector.get_columns('club')]
        
        if 'logo' in columns:
            print("Column 'logo' already exists in 'club' table.")
            return True
            
        print("Adding 'logo' column to 'club' table...")
        with engine.connect() as connection:
            connection.execute(text("ALTER TABLE club ADD COLUMN logo VARCHAR(255)"))
            connection.commit()
            
        print("Successfully added 'logo' column.")
        return True
            
    except Exception as e:
        print(f"Error adding column: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = add_logo_column()
    if success:
        print("Migration completed successfully.")
        sys.exit(0)
    else:
        print("Migration failed.")
        sys.exit(1)
