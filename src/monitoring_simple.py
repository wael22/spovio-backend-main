# src/monitoring_simple.py

"""
Système de monitoring simple pour PadelVar
Utilisation recommandée dans le guide INSTRUCTIONS_FIX_LOCAL.md
"""

import psutil
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def check_system():
    """
    Monitoring simple recommandé dans le guide fix
    Vérifie la mémoire et nettoie les processus FFmpeg anciens
    """
    try:
        memory = psutil.virtual_memory()
        
        # Alerte si mémoire élevée
        if memory.percent > 80:
            warning_msg = f"⚠️ {datetime.now()}: Mémoire élevée {memory.percent:.1f}%"
            print(warning_msg)
            logger.warning(warning_msg)
        
        # Auto-nettoyage FFmpeg anciens (comme recommandé dans le guide)
        cleaned_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'create_time']):
            try:
                if 'ffmpeg' in proc.info['name'].lower():
                    uptime = time.time() - proc.info['create_time']
                    if uptime > 3600:  # Plus d'1h
                        proc.terminate()
                        cleaned_processes.append(proc.info['pid'])
                        print(f"🧹 FFmpeg zombie nettoyé: PID {proc.info['pid']}")
                        logger.info(f"FFmpeg zombie terminated: PID {proc.info['pid']}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass  # Processus déjà terminé ou pas d'accès
            except Exception as e:
                logger.warning(f"Erreur lors du nettoyage FFmpeg: {e}")
        
        # Retourner les statistiques
        return {
            'memory_percent': memory.percent,
            'memory_ok': memory.percent < 80,
            'ffmpeg_cleaned': len(cleaned_processes),
            'cleaned_pids': cleaned_processes,
            'timestamp': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Erreur lors du monitoring système: {e}")
        return {'error': str(e)}

def memory_check_alert():
    """Check mémoire avec alerte si critique"""
    memory = psutil.virtual_memory()
    if memory.percent > 85:
        print(f"🚨 CRITIQUE: Mémoire {memory.percent:.1f}%")
        return False
    elif memory.percent > 70:
        print(f"⚠️ ATTENTION: Mémoire {memory.percent:.1f}%")  
        return False
    else:
        print(f"✅ Mémoire OK: {memory.percent:.1f}%")
        return True

def ffmpeg_process_check():
    """Vérification et nettoyage des processus FFmpeg"""
    ffmpeg_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'create_time']):
        try:
            if 'ffmpeg' in proc.info['name'].lower():
                uptime = time.time() - proc.info['create_time']
                ffmpeg_processes.append({
                    'pid': proc.info['pid'],
                    'uptime': uptime
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    if not ffmpeg_processes:
        print("✅ Aucun processus FFmpeg actif")
        return True
    
    # Alerte si processus anciens
    old_processes = [p for p in ffmpeg_processes if p['uptime'] > 7200]  # >2h
    if old_processes:
        print(f"🚨 {len(old_processes)} processus FFmpeg très anciens détectés")
        return False
    
    print(f"ℹ️  {len(ffmpeg_processes)} processus FFmpeg actifs")
    return True

# Intégration dans l'app principale (optionnel)
def monitor_periodically(app):
    """
    Fonction pour intégrer le monitoring dans l'application Flask
    À appeler périodiquement (par exemple avec APScheduler)
    """
    with app.app_context():
        return check_system()