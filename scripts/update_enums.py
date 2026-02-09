
import os
import sys
import logging

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main import create_app
from src.models.database import db
from sqlalchemy import text

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def update_enums():
    logger.info("Starting Enum update...")
    app = create_minimal_app() # create_app might be too heavy with scheduler, etc.
    # Actually, main.py create_app starts schedulers which is bad for a script.
    # Let's try to make a minimal app context.
    
    with app.app_context():
        try:
            with db.engine.connect() as conn:
                # Add VIDEO_SHARED
                logger.info("Adding VIDEO_SHARED to notificationtype...")
                try:
                    conn.execute(text("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'VIDEO_SHARED'"))
                    logger.info("Success: VIDEO_SHARED")
                except Exception as e:
                    logger.warning(f"Could not add VIDEO_SHARED (might exist on older PG): {e}")

                # Add SUPPORT
                logger.info("Adding SUPPORT to notificationtype...")
                try:
                    conn.execute(text("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'SUPPORT'"))
                    logger.info("Success: SUPPORT")
                except Exception as e:
                    logger.warning(f"Could not add SUPPORT: {e}")
                
                conn.commit()
                logger.info("Enum update committed.")
        except Exception as e:
            logger.error(f"Database error: {e}")

def create_minimal_app():
    from flask import Flask
    from src.config import get_config
    
    app = Flask(__name__)
    app.config.from_object(get_config())
    
    # Initialize DB
    db.init_app(app)
    
    return app

if __name__ == "__main__":
    update_enums()
