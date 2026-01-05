"""
API de diagnostic et monitoring du système d'enregistrement
Endpoints pour consulter les logs et détecter les problèmes
"""

from flask import Blueprint, jsonify, request
from ..routes.auth import require_auth, get_current_user
from datetime import datetime
from src.services.logging_service import get_logger, LogLevel
import os

# Blueprint pour les endpoints de diagnostic
diagnostic_bp = Blueprint('diagnostic', __name__, url_prefix='/api/diagnostic')
system_logger = get_logger()

def api_response(success, message, data=None, status_code=200):
    """Helper pour formater les réponses API"""
    response = {
        'success': success,
        'message': message
    }
    if data is not None:
        response['data'] = data
    return jsonify(response), status_code

@diagnostic_bp.route('/health', methods=['GET'])
@require_auth
def get_system_health():
    """Retourne l'état de santé global du système"""
    try:
        health_data = system_logger.get_system_health()
        
        # Déterminer le niveau global
        if health_data['recent_problems'] == 0:
            health_level = "HEALTHY"
        elif health_data['recent_problems'] <= 3:
            health_level = "WARNING"
        else:
            health_level = "CRITICAL"
        
        return api_response(True, "État de santé récupéré", {
            'system_health': health_data,
            'level': health_level,
            'recommendations': _get_health_recommendations(health_data)
        })
        
    except Exception as e:
        system_logger.log(LogLevel.ERROR, "DiagnosticAPI", f"Erreur récupération santé: {e}")
        return api_response(False, f"Erreur récupération état de santé: {e}", status_code=500)

@diagnostic_bp.route('/logs', methods=['GET'])
@require_auth
def get_recent_logs():
    """Récupère les logs récents avec filtrage"""
    try:
        # Paramètres de filtrage
        hours = int(request.args.get('hours', 1))
        level = request.args.get('level')  # DEBUG, INFO, WARNING, ERROR, CRITICAL
        component = request.args.get('component')  # Filtre par composant
        
        # Récupérer les logs
        logs = system_logger.get_recent_logs(hours=hours, level=level)
        
        # Filtrer par composant si spécifié
        if component:
            logs = [log for log in logs if component.lower() in log.get('component', '').lower()]
        
        # Limiter les résultats pour éviter la surcharge
        max_results = int(request.args.get('limit', 100))
        logs = logs[:max_results]
        
        return api_response(True, f"{len(logs)} logs récupérés", {
            'logs': logs,
            'filters': {
                'hours': hours,
                'level': level,
                'component': component,
                'limit': max_results
            }
        })
        
    except Exception as e:
        system_logger.log_error("DiagnosticAPI", f"Erreur récupération logs: {e}")
        return api_response(False, f"Erreur récupération logs: {e}", status_code=500)

@diagnostic_bp.route('/problems', methods=['GET'])
@require_auth
def get_detected_problems():
    """Récupère les problèmes détectés automatiquement"""
    try:
        # Récupérer tous les problèmes ou les plus récents
        hours = int(request.args.get('hours', 24))  # 24h par défaut
        severity = request.args.get('severity')  # HIGH, MEDIUM, LOW
        
        all_problems = system_logger.problems_detected
        
        # Filtrer par période
        from datetime import datetime, timedelta
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        recent_problems = [
            p for p in all_problems 
            if datetime.fromisoformat(p['timestamp']) > cutoff_time
        ]
        
        # Filtrer par sévérité
        if severity:
            recent_problems = [p for p in recent_problems if p.get('severity') == severity.upper()]
        
        # Grouper par type
        problems_by_type = {}
        for problem in recent_problems:
            problem_type = problem['type']
            if problem_type not in problems_by_type:
                problems_by_type[problem_type] = []
            problems_by_type[problem_type].append(problem)
        
        return api_response(True, f"{len(recent_problems)} problèmes détectés", {
            'problems': recent_problems,
            'problems_by_type': problems_by_type,
            'summary': {
                'total': len(recent_problems),
                'by_severity': _group_by_severity(recent_problems),
                'most_common': _get_most_common_problems(recent_problems)
            }
        })
        
    except Exception as e:
        system_logger.log_error("DiagnosticAPI", f"Erreur récupération problèmes: {e}")
        return api_response(False, f"Erreur récupération problèmes: {e}", status_code=500)

@diagnostic_bp.route('/metrics', methods=['GET'])
@require_auth
def get_system_metrics():
    """Récupère les métriques système en temps réel"""
    try:
        import psutil
        
        # Métriques système actuelles
        current_metrics = {
            'timestamp': datetime.now().isoformat(),
            'cpu': {
                'percent': psutil.cpu_percent(interval=1),
                'count': psutil.cpu_count(),
                'freq': psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None
            },
            'memory': {
                'total': psutil.virtual_memory().total,
                'available': psutil.virtual_memory().available,
                'percent': psutil.virtual_memory().percent,
                'used': psutil.virtual_memory().used
            },
            'disk': {
                'total': psutil.disk_usage('.').total,
                'used': psutil.disk_usage('.').used,
                'free': psutil.disk_usage('.').free,
                'percent': (psutil.disk_usage('.').used / psutil.disk_usage('.').total) * 100
            },
            'processes': {
                'total': len(psutil.pids()),
                'running': len([p for p in psutil.process_iter(['status']) if p.info['status'] == 'running'])
            }
        }
        
        # Métriques historiques du système de logging
        historical_metrics = {
            'cpu_usage': system_logger.system_metrics.get('cpu_usage', [])[-20:],  # 20 derniers points
            'memory_usage': system_logger.system_metrics.get('memory_usage', [])[-20:],
            'disk_usage': system_logger.system_metrics.get('disk_usage', [])[-20:],
            'active_recordings': len(system_logger.system_metrics.get('active_recordings', {})),
            'failed_recordings': len(system_logger.system_metrics.get('failed_recordings', []))
        }
        
        return api_response(True, "Métriques système récupérées", {
            'current': current_metrics,
            'historical': historical_metrics,
            'monitoring_active': system_logger.monitoring_active
        })
        
    except Exception as e:
        system_logger.log_error("DiagnosticAPI", f"Erreur récupération métriques: {e}")
        return api_response(False, f"Erreur récupération métriques: {e}", status_code=500)

@diagnostic_bp.route('/recordings/status', methods=['GET'])
@require_auth
def get_recordings_status():
    """Récupère le statut détaillé des enregistrements"""
    try:
        from src.services.video_recording_engine import recording_engine
        
        # Enregistrements actifs
        active_recordings = {}
        if hasattr(recording_engine, '_active_recordings'):
            for session_id, state in recording_engine._active_recordings.items():
                active_recordings[session_id] = {
                    'session_id': session_id,
                    'court_id': state.get('court_id'),
                    'user_id': state.get('user_id'),
                    'method': state.get('method'),
                    'state': state.get('state'),
                    'start_time': state.get('start_time').isoformat() if state.get('start_time') else None,
                    'duration': (datetime.now() - state.get('start_time')).total_seconds() if state.get('start_time') else 0,
                    'process_pid': state.get('process_pid'),
                    'stats': state.get('stats', {})
                }
        
        # Enregistrements échoués récents
        failed_recordings = system_logger.system_metrics.get('failed_recordings', [])[-10:]  # 10 derniers
        
        return api_response(True, "Statut enregistrements récupéré", {
            'active_recordings': active_recordings,
            'active_count': len(active_recordings),
            'failed_recordings': failed_recordings,
            'failed_count': len(failed_recordings)
        })
        
    except Exception as e:
        system_logger.log_error("DiagnosticAPI", f"Erreur récupération statut enregistrements: {e}")
        return api_response(False, f"Erreur récupération statut: {e}", status_code=500)

@diagnostic_bp.route('/cleanup', methods=['POST'])
@require_auth
def cleanup_logs():
    """Nettoie les anciens logs (admin uniquement)"""
    try:
        if not get_current_user().is_admin:
            return api_response(False, "Accès refusé - droits admin requis", status_code=403)
        
        days_to_keep = int(request.json.get('days_to_keep', 7))
        
        system_logger.cleanup_old_logs(days_to_keep)
        
        return api_response(True, f"Nettoyage effectué - logs conservés: {days_to_keep} jours")
        
    except Exception as e:
        system_logger.log_error("DiagnosticAPI", f"Erreur nettoyage logs: {e}")
        return api_response(False, f"Erreur nettoyage: {e}", status_code=500)

@diagnostic_bp.route('/monitoring/start', methods=['POST'])
@require_auth
def start_monitoring():
    """Démarre le monitoring système (admin uniquement)"""
    try:
        if not get_current_user().is_admin:
            return api_response(False, "Accès refusé - droits admin requis", status_code=403)
        
        system_logger.start_monitoring()
        
        return api_response(True, "Monitoring système démarré")
        
    except Exception as e:
        system_logger.log_error("DiagnosticAPI", f"Erreur démarrage monitoring: {e}")
        return api_response(False, f"Erreur démarrage monitoring: {e}", status_code=500)

@diagnostic_bp.route('/monitoring/stop', methods=['POST'])
@require_auth
def stop_monitoring():
    """Arrête le monitoring système (admin uniquement)"""
    try:
        if not get_current_user().is_admin:
            return api_response(False, "Accès refusé - droits admin requis", status_code=403)
        
        system_logger.stop_monitoring()
        
        return api_response(True, "Monitoring système arrêté")
        
    except Exception as e:
        system_logger.log_error("DiagnosticAPI", f"Erreur arrêt monitoring: {e}")
        return api_response(False, f"Erreur arrêt monitoring: {e}", status_code=500)

def _get_health_recommendations(health_data):
    """Génère des recommandations basées sur l'état de santé"""
    recommendations = []
    
    # CPU élevé
    if health_data['system_metrics']['avg_cpu_1h'] > 80:
        recommendations.append({
            'type': 'CPU_HIGH',
            'message': 'Utilisation CPU élevée détectée',
            'action': 'Vérifiez les processus en cours et considérez limiter les enregistrements simultanés'
        })
    
    # Mémoire élevée
    if health_data['system_metrics']['avg_memory_1h'] > 85:
        recommendations.append({
            'type': 'MEMORY_HIGH',
            'message': 'Utilisation mémoire élevée détectée',
            'action': 'Redémarrez le service ou augmentez la mémoire disponible'
        })
    
    # Disque faible
    if health_data['system_metrics']['disk_free_gb'] < 5:
        recommendations.append({
            'type': 'DISK_LOW',
            'message': 'Espace disque faible',
            'action': 'Nettoyez les anciens fichiers vidéo ou augmentez l\'espace disque'
        })
    
    # Problèmes récents
    if health_data['recent_problems'] > 0:
        recommendations.append({
            'type': 'PROBLEMS_DETECTED',
            'message': f'{health_data["recent_problems"]} problèmes détectés récemment',
            'action': 'Consultez les logs détaillés et les problèmes spécifiques'
        })
    
    return recommendations

def _group_by_severity(problems):
    """Groupe les problèmes par niveau de sévérité"""
    severity_counts = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
    for problem in problems:
        severity = problem.get('severity', 'LOW')
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    return severity_counts

def _get_most_common_problems(problems):
    """Identifie les types de problèmes les plus fréquents"""
    problem_counts = {}
    for problem in problems:
        problem_type = problem['type']
        problem_counts[problem_type] = problem_counts.get(problem_type, 0) + 1
    
    # Trier par fréquence
    sorted_problems = sorted(problem_counts.items(), key=lambda x: x[1], reverse=True)
    return sorted_problems[:5]  # Top 5
