#!/usr/bin/env python
"""
Initialize database with all tables
Run once on Railway to create all tables in PostgreSQL
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.main import create_app
from src.models.database import db

def init_db():
    """Create all database tables"""
    print("🔄 Initializing database...")
    
    app = create_app()
    
    with app.app_context():
        # Create all tables
        db.create_all()
        print("✅ All tables created successfully!")
        
        # List created tables
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"\n📊 Created {len(tables)} tables:")
        for table in sorted(tables):
            print(f"  - {table}")
    
    return True

if __name__ == '__main__':
    try:
        init_db()
        print("\n🎉 Database initialization complete!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error initializing database: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
