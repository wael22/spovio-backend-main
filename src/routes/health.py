# src/routes/health.py

"""
Routes pour les health checks et le monitoring
Exposent l'état du système pour les outils de monitoring externes
"""

import logging
from flask import Blueprint, jsonify, request
from datetime import datetime

from ..services.monitoring_service import MonitoringService
from ..routes.auth import token_required
from ..models.user import UserRole

logger = logging.getLogger(__name__)

health_bp = Blueprint('health', __name__)
monitoring_service = MonitoringService()

@health_bp.route('/health', methods=['GET'])
def basic_health_check():
    """
    Health check basique pour les load balancers
    Retourne 200 si le service est opérationnel, 503 sinon
    """
    try:
        # Check minimal : base de données disponible
        from ..models.database import db
        db.session.execute('SELECT 1').scalar()
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'service': 'padelvar-backend'
        }), 200
        
    except Exception as e:
        logger.error(f"Basic health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'timestamp': datetime.utcnow().isoformat(),
            'service': 'padelvar-backend',
            'error': str(e)
        }), 503

@health_bp.route('/health/detailed', methods=['GET'])
def detailed_health_check():
    """
    Health check détaillé avec toutes les vérifications
    """
    try:
        health_status = monitoring_service.get_system_health()
        
        # Déterminer le code de statut HTTP
        if health_status['status'] == 'healthy':
            status_code = 200
        elif health_status['status'] == 'warning':
            status_code = 200  # Warning n'est pas critique
        else:
            status_code = 503  # unhealthy ou critical
        
        return jsonify(health_status), status_code
        
    except Exception as e:
        logger.error(f"Detailed health check failed: {e}")
        return jsonify({
            'status': 'error',
            'timestamp': datetime.utcnow().isoformat(),
            'error': 'Health check service unavailable',
            'details': str(e)
        }), 503

@health_bp.route('/health/live', methods=['GET'])
def liveness_probe():
    """
    Liveness probe pour Kubernetes
    Vérifie si l'application doit être redémarrée
    """
    try:
        # Vérifications minimales pour liveness
        # - Application démarre et répond
        # - Base de données accessible
        
        from ..models.database import db
        db.session.execute('SELECT 1').scalar()
        
        return jsonify({
            'status': 'alive',
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Liveness probe failed: {e}")
        return jsonify({
            'status': 'dead',
            'timestamp': datetime.utcnow().isoformat(),
            'error': str(e)
        }), 503

@health_bp.route('/health/ready', methods=['GET'])
def readiness_probe():
    """
    Readiness probe pour Kubernetes
    Vérifie si l'application est prête à recevoir du trafic
    """
    try:
        # Vérifications pour readiness
        # - Base de données disponible
        # - Redis disponible (si configuré)
        # - Dépendances externes accessibles
        
        health_checks = monitoring_service.get_system_health()
        
        # Vérifier les composants critiques
        critical_components = ['database']
        for component in critical_components:
            if component in health_checks['checks']:
                if health_checks['checks'][component]['status'] in ['unhealthy', 'critical']:
                    return jsonify({
                        'status': 'not_ready',
                        'timestamp': datetime.utcnow().isoformat(),
                        'reason': f'{component} is not healthy'
                    }), 503
        
        return jsonify({
            'status': 'ready',
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Readiness probe failed: {e}")
        return jsonify({
            'status': 'not_ready',
            'timestamp': datetime.utcnow().isoformat(),
            'error': str(e)
        }), 503

@health_bp.route('/metrics', methods=['GET'])
def prometheus_metrics():
    """
    Métriques au format Prometheus
    """
    try:
        metrics = monitoring_service.get_system_metrics()
        
        # Convertir en format Prometheus
        prometheus_lines = []
        
        # Métriques système
        system_metrics = metrics.get('system', {})
        prometheus_lines.extend([
            f"# HELP padelvar_cpu_percent CPU usage percentage",
            f"# TYPE padelvar_cpu_percent gauge",
            f"padelvar_cpu_percent {system_metrics.get('cpu_percent', 0)}",
            f"",
            f"# HELP padelvar_memory_percent Memory usage percentage", 
            f"# TYPE padelvar_memory_percent gauge",
            f"padelvar_memory_percent {system_metrics.get('memory_percent', 0)}",
            f"",
            f"# HELP padelvar_disk_used_percent Disk usage percentage",
            f"# TYPE padelvar_disk_used_percent gauge", 
            f"padelvar_disk_used_percent {system_metrics.get('disk_used_percent', 0)}",
            f""
        ])
        
        # Métriques de base de données
        db_metrics = metrics.get('database', {})
        if 'users_total' in db_metrics:
            prometheus_lines.extend([
                f"# HELP padelvar_users_total Total number of users",
                f"# TYPE padelvar_users_total gauge",
                f"padelvar_users_total {db_metrics['users_total']}",
                f"",
                f"# HELP padelvar_active_sessions Active recording sessions",
                f"# TYPE padelvar_active_sessions gauge", 
                f"padelvar_active_sessions {db_metrics.get('active_recording_sessions', 0)}",
                f"",
                f"# HELP padelvar_recordings_total Total recordings",
                f"# TYPE padelvar_recordings_total gauge",
                f"padelvar_recordings_total {db_metrics.get('recordings_total', 0)}",
                f""
            ])
        
        # Métriques applicatives  
        app_metrics = metrics.get('application', {})
        prometheus_lines.extend([
            f"# HELP padelvar_uptime_seconds Application uptime in seconds",
            f"# TYPE padelvar_uptime_seconds counter",
            f"padelvar_uptime_seconds {app_metrics.get('uptime_seconds', 0)}",
            f""
        ])
        
        # Métriques business
        business_metrics = metrics.get('business', {})
        if 'new_users_24h' in business_metrics:
            prometheus_lines.extend([
                f"# HELP padelvar_new_users_24h New users in last 24 hours",
                f"# TYPE padelvar_new_users_24h gauge",
                f"padelvar_new_users_24h {business_metrics['new_users_24h']}",
                f"",
                f"# HELP padelvar_new_recordings_24h New recordings in last 24 hours", 
                f"# TYPE padelvar_new_recordings_24h gauge",
                f"padelvar_new_recordings_24h {business_metrics['new_recordings_24h']}",
                f""
            ])
        
        response_text = '\n'.join(prometheus_lines)
        
        from flask import Response
        return Response(response_text, mimetype='text/plain'), 200
        
    except Exception as e:
        logger.error(f"Error generating Prometheus metrics: {e}")
        return jsonify({
            'error': 'Metrics generation failed',
            'details': str(e)
        }), 500

@health_bp.route('/api/monitoring/health', methods=['GET'])
@token_required
def api_health_check(current_user):
    """
    Health check pour l'API (authentification requise)
    """
    try:
        # Vérifier que l'utilisateur est admin pour les détails complets
        from ..models.user import UserRole
        
        if current_user.role == UserRole.SUPER_ADMIN:
            # Admin : santé complète
            health_status = monitoring_service.get_system_health()
            return jsonify(health_status), 200
        else:
            # Utilisateur normal : santé basique
            return jsonify({
                'status': 'healthy',
                'timestamp': datetime.utcnow().isoformat(),
                'user_authenticated': True,
                'user_id': current_user.id
            }), 200
        
    except Exception as e:
        logger.error(f"API health check failed: {e}")
        return jsonify({
            'error': 'Health check failed',
            'details': str(e)
        }), 500

@health_bp.route('/api/monitoring/metrics', methods=['GET'])
@token_required  
def api_metrics(current_user):
    """
    Métriques système pour l'API (admin uniquement)
    """
    try:
        # Vérifier les droits admin
        from ..models.user import UserRole
        if current_user.role != UserRole.SUPER_ADMIN:
            return jsonify({'error': 'Admin access required'}), 403
        
        metrics = monitoring_service.get_system_metrics()
        return jsonify(metrics), 200
        
    except Exception as e:
        logger.error(f"Error retrieving metrics: {e}")
        return jsonify({
            'error': 'Failed to retrieve metrics',
            'details': str(e)
        }), 500

@health_bp.route('/api/monitoring/alerts', methods=['GET'])
@token_required
def get_system_alerts(current_user):
    """
    Récupère les alertes système actives (admin uniquement)
    """
    try:
        # Vérifier les droits admin
        from ..models.user import UserRole
        if current_user.role != UserRole.SUPER_ADMIN:
            return jsonify({'error': 'Admin access required'}), 403
        
        health_status = monitoring_service.get_system_health()
        
        # Extraire les alertes (statuts warning, unhealthy, critical)
        alerts = []
        
        for check_name, check_result in health_status.get('checks', {}).items():
            status = check_result.get('status')
            
            if status in ['warning', 'unhealthy', 'critical']:
                severity = {
                    'warning': 'warning',
                    'unhealthy': 'error', 
                    'critical': 'critical'
                }.get(status, 'info')
                
                alerts.append({
                    'component': check_name,
                    'severity': severity,
                    'message': check_result.get('message', 'Unknown issue'),
                    'timestamp': health_status['timestamp'],
                    'details': {k: v for k, v in check_result.items() if k not in ['status', 'message']}
                })
        
        return jsonify({
            'alerts': alerts,
            'total_alerts': len(alerts),
            'system_status': health_status['status'],
            'timestamp': health_status['timestamp']
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving alerts: {e}")
        return jsonify({
            'error': 'Failed to retrieve alerts',
            'details': str(e)
        }), 500

@health_bp.route('/api/monitoring/component/<component_name>', methods=['GET'])
@token_required
def get_component_health(current_user, component_name):
    """
    Récupère l'état d'un composant spécifique (admin uniquement)
    """
    try:
        # Vérifier les droits admin
        from ..models.user import UserRole
        if current_user.role != UserRole.SUPER_ADMIN:
            return jsonify({'error': 'Admin access required'}), 403
        
        health_status = monitoring_service.get_system_health()
        
        if component_name not in health_status.get('checks', {}):
            return jsonify({
                'error': f'Component {component_name} not found',
                'available_components': list(health_status.get('checks', {}).keys())
            }), 404
        
        component_health = health_status['checks'][component_name]
        
        return jsonify({
            'component': component_name,
            'health': component_health,
            'checked_at': health_status['timestamp']
        }), 200
        
    except Exception as e:
        logger.error(f"Error retrieving component health: {e}")
        return jsonify({
            'error': f'Failed to retrieve health for component {component_name}',
            'details': str(e)
        }), 500

# Route de debug pour le développement
@health_bp.route('/debug/info', methods=['GET'])
def debug_info():
    """
    Informations de debug (uniquement en mode développement)
    """
    from ..config import Config
    
    if not Config.DEBUG:
        return jsonify({'error': 'Debug endpoint not available in production'}), 403
    
    try:
        import sys
        import platform
        
        info = {
            'python_version': sys.version,
            'platform': platform.platform(),
            'flask_env': Config.FLASK_ENV,
            'debug_mode': Config.DEBUG,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return jsonify(info), 200
        
    except Exception as e:
        return jsonify({
            'error': 'Failed to retrieve debug info',
            'details': str(e)
        }), 500