# src/services/monitoring_service.py

"""
Service de monitoring et health checks pour PadelVar
Surveille l'état des composants critiques du système
"""

import os
import logging
import psutil
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import redis
import subprocess

from ..models.database import db
from ..models.user import User, RecordingSession, Transaction, Notification
from ..models.recording import Recording
from ..config import Config

logger = logging.getLogger(__name__)

class MonitoringService:
    """Service de monitoring complet du système"""
    
    def __init__(self):
        self.start_time = datetime.utcnow()
        self._redis_client = None
        self._last_health_check = {}
    
    def get_system_health(self) -> Dict[str, Any]:
        """
        Récupère l'état de santé complet du système
        """
        health_status = {
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'uptime_seconds': self._get_uptime_seconds(),
            'version': Config.VERSION if hasattr(Config, 'VERSION') else '1.0.0',
            'environment': Config.FLASK_ENV,
            'checks': {}
        }
        
        # Vérifications critiques
        critical_checks = {
            'database': self._check_database,
            'redis': self._check_redis,
            'disk_space': self._check_disk_space,
            'memory': self._check_memory,
            'celery': self._check_celery_workers,
        }
        
        # Vérifications non-critiques
        warning_checks = {
            'ffmpeg': self._check_ffmpeg,
            'temp_files': self._check_temp_files,
            'zombie_sessions': self._check_zombie_sessions,
            'pending_uploads': self._check_pending_uploads,
        }
        
        overall_status = 'healthy'
        
        # Exécuter les vérifications critiques
        for check_name, check_func in critical_checks.items():
            try:
                result = check_func()
                health_status['checks'][check_name] = result
                
                if result['status'] in ['unhealthy', 'critical']:
                    overall_status = 'unhealthy'
                elif result['status'] == 'warning' and overall_status == 'healthy':
                    overall_status = 'warning'
                    
            except Exception as e:
                logger.error(f"Erreur lors du check {check_name}: {e}")
                health_status['checks'][check_name] = {
                    'status': 'error',
                    'message': str(e)
                }
                overall_status = 'unhealthy'
        
        # Exécuter les vérifications d'avertissement
        for check_name, check_func in warning_checks.items():
            try:
                result = check_func()
                health_status['checks'][check_name] = result
                
                if result['status'] == 'warning' and overall_status == 'healthy':
                    overall_status = 'warning'
                    
            except Exception as e:
                logger.warning(f"Erreur lors du check {check_name}: {e}")
                health_status['checks'][check_name] = {
                    'status': 'error',
                    'message': str(e)
                }
        
        health_status['status'] = overall_status
        self._last_health_check = health_status
        
        return health_status
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """
        Récupère les métriques détaillées du système
        """
        metrics = {
            'timestamp': datetime.utcnow().isoformat(),
            'system': self._get_system_metrics(),
            'database': self._get_database_metrics(),
            'application': self._get_application_metrics(),
            'business': self._get_business_metrics()
        }
        
        return metrics
    
    def _get_uptime_seconds(self) -> int:
        """Calcule l'uptime en secondes"""
        return int((datetime.utcnow() - self.start_time).total_seconds())
    
    def _check_database(self) -> Dict[str, Any]:
        """Vérifie l'état de la base de données"""
        try:
            start_time = time.time()
            
            # Test de connexion simple
            result = db.session.execute('SELECT 1').scalar()
            
            response_time = (time.time() - start_time) * 1000  # en ms
            
            if result != 1:
                return {
                    'status': 'unhealthy',
                    'message': 'Database query returned unexpected result'
                }
            
            # Vérifier le temps de réponse
            if response_time > 1000:  # Plus de 1 seconde
                return {
                    'status': 'warning',
                    'message': f'Database response time is slow: {response_time:.2f}ms',
                    'response_time_ms': response_time
                }
            
            return {
                'status': 'healthy',
                'message': 'Database is responsive',
                'response_time_ms': response_time
            }
            
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f'Database connection failed: {str(e)}'
            }
    
    def _check_redis(self) -> Dict[str, Any]:
        """Vérifie l'état de Redis"""
        try:
            if not self._redis_client:
                redis_url = Config.CELERY_BROKER_URL
                if redis_url:
                    self._redis_client = redis.from_url(redis_url, decode_responses=True)
                else:
                    return {
                        'status': 'warning',
                        'message': 'Redis not configured'
                    }
            
            start_time = time.time()
            self._redis_client.ping()
            response_time = (time.time() - start_time) * 1000
            
            # Vérifier les métriques Redis
            info = self._redis_client.info()
            memory_used = info.get('used_memory', 0)
            connected_clients = info.get('connected_clients', 0)
            
            status = 'healthy'
            messages = []
            
            if response_time > 100:  # Plus de 100ms
                status = 'warning'
                messages.append(f'Slow response: {response_time:.2f}ms')
            
            if connected_clients > 100:
                status = 'warning'
                messages.append(f'High client connections: {connected_clients}')
            
            return {
                'status': status,
                'message': '; '.join(messages) if messages else 'Redis is healthy',
                'response_time_ms': response_time,
                'memory_used_bytes': memory_used,
                'connected_clients': connected_clients
            }
            
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f'Redis connection failed: {str(e)}'
            }
    
    def _check_disk_space(self) -> Dict[str, Any]:
        """Vérifie l'espace disque disponible"""
        try:
            # Vérifier l'espace pour différents points de montage
            checks = {}
            overall_status = 'healthy'
            
            # Répertoire racine
            root_usage = psutil.disk_usage('/')
            root_percent = (root_usage.used / root_usage.total) * 100
            
            checks['root'] = {
                'used_percent': round(root_percent, 2),
                'free_gb': round(root_usage.free / (1024**3), 2),
                'total_gb': round(root_usage.total / (1024**3), 2)
            }
            
            if root_percent > 90:
                overall_status = 'critical'
            elif root_percent > 80:
                overall_status = 'warning'
            
            # Répertoire temporaire
            try:
                tmp_usage = psutil.disk_usage('/tmp')
                tmp_percent = (tmp_usage.used / tmp_usage.total) * 100
                
                checks['tmp'] = {
                    'used_percent': round(tmp_percent, 2),
                    'free_gb': round(tmp_usage.free / (1024**3), 2)
                }
                
                if tmp_percent > 95:
                    overall_status = 'critical'
                elif tmp_percent > 85 and overall_status == 'healthy':
                    overall_status = 'warning'
                    
            except Exception:
                pass  # /tmp peut ne pas être accessible
            
            return {
                'status': overall_status,
                'message': f'Root disk usage: {root_percent:.1f}%',
                'details': checks
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Failed to check disk space: {str(e)}'
            }
    
    def _check_memory(self) -> Dict[str, Any]:
        """Vérifie l'utilisation mémoire"""
        try:
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            memory_percent = memory.percent
            swap_percent = swap.percent
            
            status = 'healthy'
            messages = []
            
            if memory_percent > 90:
                status = 'critical'
                messages.append(f'Critical memory usage: {memory_percent:.1f}%')
            elif memory_percent > 80:
                status = 'warning'
                messages.append(f'High memory usage: {memory_percent:.1f}%')
            
            if swap_percent > 50:
                if status == 'healthy':
                    status = 'warning'
                messages.append(f'High swap usage: {swap_percent:.1f}%')
            
            return {
                'status': status,
                'message': '; '.join(messages) if messages else f'Memory usage: {memory_percent:.1f}%',
                'memory_percent': memory_percent,
                'memory_available_gb': round(memory.available / (1024**3), 2),
                'swap_percent': swap_percent
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Failed to check memory: {str(e)}'
            }
    
    def _check_celery_workers(self) -> Dict[str, Any]:
        """Vérifie l'état des workers Celery"""
        try:
            if not self._redis_client:
                return {
                    'status': 'warning',
                    'message': 'Cannot check Celery without Redis connection'
                }
            
            # Vérifier les workers actifs (via Celery inspect)
            from celery import Celery
            from ..celery_app import celery_app
            
            inspect = celery_app.control.inspect()
            
            # Récupérer les workers actifs
            active_workers = inspect.active()
            registered_tasks = inspect.registered()
            
            if not active_workers:
                return {
                    'status': 'unhealthy',
                    'message': 'No active Celery workers found'
                }
            
            worker_count = len(active_workers)
            total_active_tasks = sum(len(tasks) for tasks in active_workers.values())
            
            status = 'healthy'
            if worker_count < 2:  # Minimum recommandé
                status = 'warning'
            
            return {
                'status': status,
                'message': f'{worker_count} workers active, {total_active_tasks} tasks running',
                'worker_count': worker_count,
                'active_tasks': total_active_tasks,
                'workers': list(active_workers.keys())
            }
            
        except Exception as e:
            return {
                'status': 'warning',
                'message': f'Cannot check Celery workers: {str(e)}'
            }
    
    def _check_ffmpeg(self) -> Dict[str, Any]:
        """Vérifie la disponibilité de FFmpeg"""
        try:
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                # Extraire la version
                version_line = result.stdout.split('\n')[0]
                return {
                    'status': 'healthy',
                    'message': 'FFmpeg is available',
                    'version': version_line
                }
            else:
                return {
                    'status': 'warning',
                    'message': f'FFmpeg check failed with code {result.returncode}'
                }
                
        except subprocess.TimeoutExpired:
            return {
                'status': 'warning',
                'message': 'FFmpeg check timed out'
            }
        except FileNotFoundError:
            return {
                'status': 'warning',
                'message': 'FFmpeg not found in PATH'
            }
        except Exception as e:
            return {
                'status': 'warning',
                'message': f'FFmpeg check error: {str(e)}'
            }
    
    def _check_temp_files(self) -> Dict[str, Any]:
        """Vérifie les fichiers temporaires"""
        try:
            temp_dir = '/tmp'
            if not os.path.exists(temp_dir):
                return {
                    'status': 'healthy',
                    'message': 'Temp directory not accessible'
                }
            
            # Compter les fichiers de recording temporaires
            recording_files = []
            total_size = 0
            old_files = 0
            
            current_time = datetime.now()
            
            for filename in os.listdir(temp_dir):
                if filename.startswith('recording_') and filename.endswith('.mp4'):
                    file_path = os.path.join(temp_dir, filename)
                    try:
                        stat = os.stat(file_path)
                        file_size = stat.st_size
                        file_time = datetime.fromtimestamp(stat.st_mtime)
                        
                        recording_files.append({
                            'filename': filename,
                            'size_mb': round(file_size / (1024 * 1024), 2),
                            'age_hours': round((current_time - file_time).total_seconds() / 3600, 1)
                        })
                        
                        total_size += file_size
                        
                        if (current_time - file_time).total_seconds() > 86400:  # Plus de 24h
                            old_files += 1
                            
                    except Exception:
                        continue
            
            status = 'healthy'
            messages = []
            
            if len(recording_files) > 10:
                status = 'warning'
                messages.append(f'{len(recording_files)} temp recording files')
            
            if total_size > 5 * 1024 * 1024 * 1024:  # Plus de 5GB
                status = 'warning'
                messages.append(f'{round(total_size / (1024**3), 2)}GB of temp files')
            
            if old_files > 0:
                if status == 'healthy':
                    status = 'warning'
                messages.append(f'{old_files} old files (>24h)')
            
            return {
                'status': status,
                'message': '; '.join(messages) if messages else f'{len(recording_files)} temp files',
                'temp_files_count': len(recording_files),
                'total_size_mb': round(total_size / (1024 * 1024), 2),
                'old_files_count': old_files
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Failed to check temp files: {str(e)}'
            }
    
    def _check_zombie_sessions(self) -> Dict[str, Any]:
        """Vérifie les sessions zombies"""
        try:
            # Chercher les sessions actives potentiellement zombies
            current_time = datetime.utcnow()
            one_hour_ago = current_time - timedelta(hours=1)
            
            # Sessions actives depuis plus d'une heure
            long_sessions = RecordingSession.query.filter(
                RecordingSession.status == 'active',
                RecordingSession.start_time < one_hour_ago
            ).all()
            
            # Sessions expirées mais non nettoyées
            expired_sessions = [session for session in long_sessions if session.is_expired()]
            
            status = 'healthy'
            if expired_sessions:
                status = 'warning'
            
            return {
                'status': status,
                'message': f'{len(expired_sessions)} zombie sessions detected' if expired_sessions else 'No zombie sessions',
                'long_running_sessions': len(long_sessions),
                'zombie_sessions': len(expired_sessions)
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Failed to check zombie sessions: {str(e)}'
            }
    
    def _check_pending_uploads(self) -> Dict[str, Any]:
        """Vérifie les uploads en attente"""
        try:
            # Uploads en cours depuis plus de 30 minutes
            thirty_minutes_ago = datetime.utcnow() - timedelta(minutes=30)
            
            stuck_uploads = Recording.query.filter(
                Recording.upload_status == 'uploading',
                Recording.created_at < thirty_minutes_ago
            ).count()
            
            failed_uploads = Recording.query.filter(
                Recording.upload_status == 'failed'
            ).count()
            
            status = 'healthy'
            messages = []
            
            if stuck_uploads > 0:
                status = 'warning'
                messages.append(f'{stuck_uploads} stuck uploads')
            
            if failed_uploads > 5:  # Plus de 5 uploads échoués
                if status == 'healthy':
                    status = 'warning'
                messages.append(f'{failed_uploads} failed uploads')
            
            return {
                'status': status,
                'message': '; '.join(messages) if messages else 'Upload status healthy',
                'stuck_uploads': stuck_uploads,
                'failed_uploads': failed_uploads
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'message': f'Failed to check uploads: {str(e)}'
            }
    
    def _get_system_metrics(self) -> Dict[str, Any]:
        """Récupère les métriques système"""
        cpu = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return {
            'cpu_percent': cpu,
            'memory_percent': memory.percent,
            'memory_used_gb': round((memory.total - memory.available) / (1024**3), 2),
            'memory_total_gb': round(memory.total / (1024**3), 2),
            'disk_used_percent': round((disk.used / disk.total) * 100, 2),
            'disk_free_gb': round(disk.free / (1024**3), 2),
            'load_average': os.getloadavg() if hasattr(os, 'getloadavg') else None
        }
    
    def _get_database_metrics(self) -> Dict[str, Any]:
        """Récupère les métriques de base de données"""
        try:
            # Compter les entités principales
            users_count = User.query.count()
            active_sessions = RecordingSession.query.filter_by(status='active').count()
            total_recordings = Recording.query.count()
            pending_transactions = Transaction.query.filter_by(status='pending').count()
            unread_notifications = Notification.query.filter_by(is_read=False).count()
            
            return {
                'users_total': users_count,
                'active_recording_sessions': active_sessions,
                'recordings_total': total_recordings,
                'pending_transactions': pending_transactions,
                'unread_notifications': unread_notifications
            }
        except Exception as e:
            logger.error(f"Error getting database metrics: {e}")
            return {'error': str(e)}
    
    def _get_application_metrics(self) -> Dict[str, Any]:
        """Récupère les métriques applicatives"""
        return {
            'uptime_seconds': self._get_uptime_seconds(),
            'environment': Config.FLASK_ENV,
            'debug_mode': Config.DEBUG,
            'last_health_check': self._last_health_check.get('timestamp') if self._last_health_check else None
        }
    
    def _get_business_metrics(self) -> Dict[str, Any]:
        """Récupère les métriques business (dernières 24h)"""
        try:
            last_24h = datetime.utcnow() - timedelta(hours=24)
            
            new_users = User.query.filter(User.created_at >= last_24h).count()
            new_recordings = Recording.query.filter(Recording.created_at >= last_24h).count()
            completed_transactions = Transaction.query.filter(
                Transaction.status == 'completed',
                Transaction.completed_at >= last_24h
            ).count()
            
            return {
                'new_users_24h': new_users,
                'new_recordings_24h': new_recordings,
                'completed_transactions_24h': completed_transactions
            }
        except Exception as e:
            logger.error(f"Error getting business metrics: {e}")
            return {'error': str(e)}