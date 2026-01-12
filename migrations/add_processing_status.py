"""
Migration: Ajouter la colonne processing_status à la table video
Date: 2026-01-10
"""

import sqlite3
import os
import logging

logger = logging.getLogger(__name__)

def migrate():
    """Ajoute la colonne processing_status à la table video"""
    
    # Chemin vers la base de données - CORRECT PATH
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance', 'padelvar.db')
    
    if not os.path.exists(db_path):
        logger.error(f"❌ Base de données introuvable: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Vérifier si la colonne existe déjà
        cursor.execute("PRAGMA table_info(video)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'processing_status' in columns:
            logger.info("✅ La colonne processing_status existe déjà")
            conn.close()
            return True
        
        # Ajouter la colonne
        logger.info("📝 Ajout de la colonne processing_status...")
        cursor.execute("""
            ALTER TABLE video 
            ADD COLUMN processing_status VARCHAR(20) DEFAULT 'pending'
        """)
        
        # Mettre à jour les vidéos existantes qui ont un bunny_video_id
        # On les marque comme 'ready' car elles sont déjà uploadées
        cursor.execute("""
            UPDATE video 
            SET processing_status = 'ready' 
            WHERE bunny_video_id IS NOT NULL 
            AND cloud_deleted_at IS NULL
        """)
        
        rows_updated = cursor.rowcount
        
        conn.commit()
        conn.close()
        
        logger.info(f"✅ Migration réussie!")
        logger.info(f"   - Colonne processing_status ajoutée")
        logger.info(f"   - {rows_updated} vidéos existantes marquées comme 'ready'")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la migration: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
