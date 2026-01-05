# src/routes/system.py

"""
Routes pour le monitoring et l'administration système
Endpoints pour consulter l'état du système, diagnostics, maintenance
"""

import logging
from flask import Blueprint, jsonify, request
from datetime import datetime

from ..routes.auth import require_auth, require_admin
from ..models.user import UserRole

logger = logging.getLogger(__name__)

system_bp = Blueprint('system', __name__)

@system_bp.route('/health', methods=['GET'])
def system_health():
    """
    Endpoint de santé système avec vérifications complètes
    Accessible à tous les utilisateurs authentifiés
    """
    try:
        from ..monitoring_simple import check_system, memory_check_alert, ffmpeg_process_check
        
        # Exécuter toutes les vérifications
        system_status = check_system()
        memory_ok = memory_check_alert()
        ffmpeg_ok = ffmpeg_process_check()
        
        overall_status = "healthy"
        if not memory_ok or not ffmpeg_ok or system_status.get('error'):
            overall_status = "warning"
        
        if system_status.get('error'):
            overall_status = "error"
        
        response = {
            'status': overall_status,
            'timestamp': datetime.utcnow().isoformat(),
            'checks': {
                'memory': {
                    'status': 'ok' if memory_ok else 'warning',
                    'percent': system_status.get('memory_percent', 0),
                    'ok': system_status.get('memory_ok', False)
                },
                'ffmpeg': {
                    'status': 'ok' if ffmpeg_ok else 'warning',
                    'cleaned_processes': system_status.get('ffmpeg_cleaned', 0)
                },
                'system': {
                    'status': 'ok' if not system_status.get('error') else 'error',
                    'details': system_status
                }
            }
        }
        
        status_code = 200
        if overall_status == "warning":
            status_code = 200  # Warning mais pas erreur
        elif overall_status == "error":
            status_code = 500
        
        return jsonify(response), status_code
        
    except Exception as e:
        logger.error(f"Erreur lors de la vérification système: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500

@system_bp.route('/metrics', methods=['GET'])
@require_auth
def system_metrics():
    """
    Métriques système détaillées
    Accessible aux utilisateurs authentifiés
    """
    try:
        from ..monitoring_simple import check_system
        import psutil
        
        # Récupérer les métriques système
        system_status = check_system()
        
        # Métriques supplémentaires
        cpu_percent = psutil.cpu_percent(interval=1)
        disk_usage = psutil.disk_usage('/')
        
        # Processus FFmpeg actifs
        ffmpeg_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'create_time', 'memory_percent']):
            try:
                if 'ffmpeg' in proc.info['name'].lower():
                    import time
                    uptime = time.time() - proc.info['create_time']
                    ffmpeg_processes.append({
                        'pid': proc.info['pid'],
                        'uptime_seconds': round(uptime),
                        'memory_percent': round(proc.info['memory_percent'], 2)
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        metrics = {
            'timestamp': datetime.utcnow().isoformat(),
            'memory': {
                'percent': system_status.get('memory_percent', 0),
                'available_gb': round(psutil.virtual_memory().available / (1024**3), 2),
                'total_gb': round(psutil.virtual_memory().total / (1024**3), 2)
            },
            'cpu': {
                'percent': cpu_percent
            },
            'disk': {
                'percent': round((disk_usage.used / disk_usage.total) * 100, 1),
                'free_gb': round(disk_usage.free / (1024**3), 2),
                'total_gb': round(disk_usage.total / (1024**3), 2)
            },
            'ffmpeg': {
                'active_processes': len(ffmpeg_processes),
                'processes': ffmpeg_processes,
                'cleaned_count': system_status.get('ffmpeg_cleaned', 0)
            },
            'system': system_status
        }
        
        return jsonify(metrics)
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des métriques: {str(e)}")
        return jsonify({'error': str(e)}), 500

@system_bp.route('/cleanup', methods=['POST'])
@require_admin
def force_cleanup():
    """
    Déclenche un nettoyage forcé du système
    Accessible uniquement aux administrateurs
    """
    try:
        # Importer et exécuter le nettoyage forcé
        from ..tasks.maintenance_tasks import force_cleanup_system
        
        # Déclencher la tâche de nettoyage
        result = force_cleanup_system.delay()
        
        # Attendre le résultat (timeout de 30 secondes)
        cleanup_result = result.get(timeout=30)
        
        return jsonify({
            'status': 'success',
            'message': 'Nettoyage forcé exécuté',
            'result': cleanup_result,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage forcé: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500

@system_bp.route('/monitoring/trigger', methods=['POST'])
@require_admin
def trigger_monitoring():
    """
    Déclenche manuellement une vérification de monitoring
    Accessible uniquement aux administrateurs
    """
    try:
        from ..tasks.maintenance_tasks import system_monitoring_check
        
        # Déclencher la tâche de monitoring
        result = system_monitoring_check.delay()
        
        # Attendre le résultat
        monitoring_result = result.get(timeout=15)
        
        return jsonify({
            'status': 'success',
            'message': 'Monitoring déclenché manuellement',
            'result': monitoring_result,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Erreur lors du déclenchement du monitoring: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500

@system_bp.route('/sessions/cleanup', methods=['POST'])
@require_admin
def cleanup_zombie_sessions():
    """
    Déclenche le nettoyage des sessions zombies
    Accessible uniquement aux administrateurs
    """
    try:
        from ..tasks.maintenance_tasks import cleanup_zombie_sessions
        
        # Déclencher la tâche de nettoyage des sessions
        result = cleanup_zombie_sessions.delay()
        
        # Attendre le résultat
        cleanup_result = result.get(timeout=30)
        
        return jsonify({
            'status': 'success',
            'message': 'Nettoyage des sessions zombies exécuté',
            'result': cleanup_result,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage des sessions: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500

@system_bp.route('/report/daily', methods=['GET'])
@require_admin  
def get_daily_report():
    """
    Récupère le rapport de santé quotidien
    Accessible uniquement aux administrateurs
    """
    try:
        from ..tasks.maintenance_tasks import generate_daily_health_report
        
        # Déclencher la génération du rapport
        result = generate_daily_health_report.delay()
        
        # Attendre le résultat
        report = result.get(timeout=20)
        
        return jsonify({
            'status': 'success',
            'report': report,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de la génération du rapport: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500