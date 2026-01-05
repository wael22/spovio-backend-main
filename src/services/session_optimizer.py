# padelvar-backend/src/services/session_optimizer.py

"""
Service d'optimisation avancée des sessions expirées
Nettoyage automatique, monitoring et performance optimisée
"""

from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_
from ..models.database import db
from ..models.user import RecordingSession, VideoRecordingLog, ClubActionHistory
import logging
import time
import threading
import schedule

logger = logging.getLogger(__name__)

class SessionOptimizer:
    """Gestionnaire avancé des sessions expirées avec optimisations performance"""
    
    def __init__(self):
        self.cleanup_running = False
        self.last_cleanup = None
        self.stats = {
            'sessions_cleaned': 0,
            'cleanup_duration': 0,
            'last_run': None
        }
    
    def cleanup_expired_sessions(self, batch_size=100, max_age_hours=24):
        """
        Nettoyage optimisé des sessions expirées en lots
        
        Args:
            batch_size: Nombre de sessions à traiter par lot
            max_age_hours: Âge maximum des sessions en heures
        """
        if self.cleanup_running:
            logger.warning("Nettoyage déjà en cours, ignoré")
            return False
            
        self.cleanup_running = True
        start_time = time.time()
        
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
            total_cleaned = 0
            
            logger.info(f"🧹 Début nettoyage sessions expirées avant {cutoff_time}")
            
            # ÉTAPE 1: Identifier les sessions expirées
            expired_sessions_query = RecordingSession.query.filter(
                and_(
                    RecordingSession.created_at < cutoff_time,
                    or_(
                        RecordingSession.status == 'abandoned',
                        RecordingSession.status == 'error',
                        and_(
                            RecordingSession.status == 'active',
                            RecordingSession.last_activity < cutoff_time
                        )
                    )
                )
            )
            
            total_expired = expired_sessions_query.count()
            logger.info(f"📊 {total_expired} sessions expirées identifiées")
            
            # ÉTAPE 2: Nettoyage par lots (optimisé pour la performance)
            while True:
                expired_batch = expired_sessions_query.limit(batch_size).all()
                if not expired_batch:
                    break
                
                batch_ids = [session.id for session in expired_batch]
                
                # Nettoyage des logs associés
                VideoRecordingLog.query.filter(
                    VideoRecordingLog.recording_session_id.in_(batch_ids)
                ).delete(synchronize_session=False)
                
                # Nettoyage des sessions
                RecordingSession.query.filter(
                    RecordingSession.id.in_(batch_ids)
                ).delete(synchronize_session=False)
                
                db.session.commit()
                total_cleaned += len(expired_batch)
                
                logger.info(f"🗑️ Lot nettoyé: {len(expired_batch)} sessions")
                
                # Pause courte pour éviter la surcharge
                time.sleep(0.1)
            
            # ÉTAPE 3: Optimisation base de données
            self._optimize_database()
            
            # ÉTAPE 4: Mise à jour statistiques
            cleanup_duration = time.time() - start_time
            self.stats.update({
                'sessions_cleaned': total_cleaned,
                'cleanup_duration': cleanup_duration,
                'last_run': datetime.utcnow().isoformat()
            })
            
            # ÉTAPE 5: Log historique de l'action
            self._log_cleanup_action(total_cleaned, cleanup_duration)
            
            logger.info(f"✅ Nettoyage terminé: {total_cleaned} sessions supprimées en {cleanup_duration:.2f}s")
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"❌ Erreur lors du nettoyage des sessions: {e}")
            return False
            
        finally:
            self.cleanup_running = False
            self.last_cleanup = datetime.utcnow()
    
    def _optimize_database(self):
        """Optimise la base de données après nettoyage"""
        try:
            # VACUUM et ANALYZE pour PostgreSQL/SQLite
            if 'postgresql' in db.engine.url.drivername:
                db.engine.execute('VACUUM ANALYZE recording_session;')
                db.engine.execute('VACUUM ANALYZE video_recording_log;')
            elif 'sqlite' in db.engine.url.drivername:
                db.engine.execute('VACUUM;')
                db.engine.execute('ANALYZE;')
                
            logger.info("🔧 Optimisation base de données terminée")
            
        except Exception as e:
            logger.warning(f"⚠️ Optimisation DB échouée: {e}")
    
    def _log_cleanup_action(self, sessions_cleaned, duration):
        """Log de l'action de nettoyage dans l'historique"""
        try:
            history_entry = ClubActionHistory(
                club_id=None,  # Action système globale
                action_type="system_cleanup",
                description=f"Nettoyage automatique: {sessions_cleaned} sessions expirées supprimées",
                details={
                    'sessions_cleaned': sessions_cleaned,
                    'duration_seconds': round(duration, 2),
                    'timestamp': datetime.utcnow().isoformat()
                },
                performed_at=datetime.utcnow(),
                performed_by_user_id=None  # Action automatique
            )
            db.session.add(history_entry)
            db.session.commit()
            
        except Exception as e:
            logger.error(f"Erreur log historique cleanup: {e}")
    
    def get_cleanup_stats(self):
        """Retourne les statistiques de nettoyage"""
        return {
            **self.stats,
            'cleanup_running': self.cleanup_running,
            'last_cleanup': self.last_cleanup.isoformat() if self.last_cleanup else None
        }
    
    def force_cleanup_now(self):
        """Force un nettoyage immédiat (pour admin)"""
        return self.cleanup_expired_sessions(batch_size=50, max_age_hours=12)

class SessionScheduler:
    """Planificateur automatique pour les tâches de session"""
    
    def __init__(self, optimizer: SessionOptimizer):
        self.optimizer = optimizer
        self.scheduler_running = False
    
    def start_scheduler(self):
        """Démarre le planificateur automatique"""
        if self.scheduler_running:
            return
            
        self.scheduler_running = True
        
        # Planifier nettoyage toutes les 4 heures
        schedule.every(4).hours.do(self.optimizer.cleanup_expired_sessions)
        
        # Planifier nettoyage quotidien approfondi (2h du matin)
        schedule.every().day.at("02:00").do(
            lambda: self.optimizer.cleanup_expired_sessions(
                batch_size=200, 
                max_age_hours=48
            )
        )
        
        # Thread de surveillance
        def run_scheduler():
            while self.scheduler_running:
                schedule.run_pending()
                time.sleep(60)  # Vérifier chaque minute
        
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        
        logger.info("📅 Planificateur de sessions démarré")
    
    def stop_scheduler(self):
        """Arrête le planificateur"""
        self.scheduler_running = False
        schedule.clear()
        logger.info("📅 Planificateur de sessions arrêté")

# Instance globale du service
session_optimizer = SessionOptimizer()
session_scheduler = SessionScheduler(session_optimizer)