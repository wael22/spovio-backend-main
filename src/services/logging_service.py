#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Service de logging avec détection automatique des problèmes
Version complète avec monitoring système
"""
import logging
import json
import os
import threading
import time
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import psutil


class LogLevel(Enum):
    """Niveaux de log avec couleurs"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ProblemType(Enum):
    """Types de problèmes détectés automatiquement"""
    FFMPEG_CRASH = "FFMPEG_CRASH"
    PHANTOM_RECORDING = "PHANTOM_RECORDING"
    UPLOAD_FAILURE = "UPLOAD_FAILURE"
    MEMORY_LEAK = "MEMORY_LEAK"
    DISK_SPACE = "DISK_SPACE"
    NETWORK_ERROR = "NETWORK_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    PROCESS_HUNG = "PROCESS_HUNG"
    HIGH_CPU = "HIGH_CPU"


class SystemLogger:
    """Logger système avec détection automatique des problèmes"""
    
    def __init__(self, logs_dir: str = "logs"):
        self.logs_dir = logs_dir
        self.log_file = os.path.join(logs_dir, f"system_{datetime.now().strftime('%Y%m%d')}.log")
        self.problems_file = os.path.join(logs_dir, f"problems_{datetime.now().strftime('%Y%m%d')}.log")
        
        # Créer le dossier logs s'il n'existe pas
        os.makedirs(logs_dir, exist_ok=True)
        
        # Configuration du logger Python standard
        self.logger = logging.getLogger("PadelVar")
        self.logger.setLevel(logging.DEBUG)
        
        # Handler pour fichier
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        
        # Handler pour console
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Format des logs
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # Éviter les doublons
        if not self.logger.handlers:
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)
        
        # Monitoring système (désactivé en développement)
        self.monitoring_active = False
        self.system_metrics = {}
        self.problems_detected = []
        self.monitoring_thread = None
        
        # Seuils de détection
        self.thresholds = {
            'cpu_usage': 90.0,      # %
            'memory_usage': 85.0,    # %
            'disk_usage': 95.0,      # %
            'process_hung_time': 300  # secondes
        }
        
        # Démarrer le monitoring
        self._start_monitoring()
        
        self.log(LogLevel.INFO, "🔧 SystemLogger initialisé avec monitoring automatique")
    
    def log(self, level: LogLevel, message: str, extra_data: Optional[Dict] = None):
        """Log un message avec niveau et données supplémentaires"""
        
        # Préparer les données du log
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level.value,
            "message": message,
            "thread": threading.current_thread().name,
            "process_id": os.getpid()
        }
        
        if extra_data:
            log_entry["extra_data"] = extra_data
        
        # Logger Python standard
        if level == LogLevel.DEBUG:
            self.logger.debug(message)
        elif level == LogLevel.INFO:
            self.logger.info(message)
        elif level == LogLevel.WARNING:
            self.logger.warning(message)
        elif level == LogLevel.ERROR:
            self.logger.error(message)
        elif level == LogLevel.CRITICAL:
            self.logger.critical(message)
        
        # Log JSON structuré
        self._write_json_log(log_entry)
        
        # Détection automatique de problèmes
        self._detect_problems(level, message, extra_data)
    
    def _write_json_log(self, log_entry: Dict):
        """Écrire un log au format JSON"""
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"Erreur écriture log: {e}")
    
    def _detect_problems(self, level: LogLevel, message: str, extra_data: Optional[Dict]):
        """Détection automatique de problèmes"""
        
        problem = None
        
        # Détection basée sur les messages
        message_lower = message.lower()
        
        if "ffmpeg" in message_lower and ("crash" in message_lower or "error" in message_lower):
            problem = ProblemType.FFMPEG_CRASH
        elif "phantom" in message_lower or "fantôme" in message_lower:
            problem = ProblemType.PHANTOM_RECORDING
        elif "upload" in message_lower and ("failed" in message_lower or "échec" in message_lower):
            problem = ProblemType.UPLOAD_FAILURE
        elif "database" in message_lower and "error" in message_lower:
            problem = ProblemType.DATABASE_ERROR
        elif "network" in message_lower and ("error" in message_lower or "timeout" in message_lower):
            problem = ProblemType.NETWORK_ERROR
        
        # Détection basée sur le niveau de log
        if level in [LogLevel.ERROR, LogLevel.CRITICAL]:
            if not problem:  # Si pas déjà détecté
                if "memory" in message_lower:
                    problem = ProblemType.MEMORY_LEAK
                elif "hung" in message_lower or "bloqué" in message_lower:
                    problem = ProblemType.PROCESS_HUNG
        
        if problem:
            self._record_problem(problem, message, extra_data)
    
    def _record_problem(self, problem_type: ProblemType, message: str, extra_data: Optional[Dict]):
        """Enregistrer un problème détecté"""
        
        problem_entry = {
            "timestamp": datetime.now().isoformat(),
            "problem_type": problem_type.value,
            "message": message,
            "system_metrics": self.system_metrics.copy(),
            "extra_data": extra_data or {}
        }
        
        self.problems_detected.append(problem_entry)
        
        # Écrire dans le fichier des problèmes
        try:
            with open(self.problems_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(problem_entry, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"Erreur écriture problème: {e}")
        
        # Log du problème détecté
        self.logger.critical(f"🚨 PROBLÈME DÉTECTÉ: {problem_type.value} - {message}")
    
    def _start_monitoring(self):
        """Démarrer le monitoring système en arrière-plan"""
        def monitoring_loop():
            while self.monitoring_active:
                try:
                    # Métriques système
                    cpu_percent = psutil.cpu_percent(interval=1)
                    memory = psutil.virtual_memory()
                    disk = psutil.disk_usage('/')
                    
                    self.system_metrics = {
                        "cpu_usage": cpu_percent,
                        "memory_usage": memory.percent,
                        "memory_available": memory.available,
                        "disk_usage": disk.percent,
                        "disk_free": disk.free,
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    # Vérification des seuils
                    if cpu_percent > self.thresholds['cpu_usage']:
                        self._record_problem(
                            ProblemType.HIGH_CPU,
                            f"Utilisation CPU élevée: {cpu_percent:.1f}%",
                            {"cpu_usage": cpu_percent}
                        )
                    
                    if memory.percent > self.thresholds['memory_usage']:
                        self._record_problem(
                            ProblemType.MEMORY_LEAK,
                            f"Utilisation mémoire élevée: {memory.percent:.1f}%",
                            {"memory_usage": memory.percent, "memory_available": memory.available}
                        )
                    
                    if disk.percent > self.thresholds['disk_usage']:
                        self._record_problem(
                            ProblemType.DISK_SPACE,
                            f"Espace disque critique: {disk.percent:.1f}%",
                            {"disk_usage": disk.percent, "disk_free": disk.free}
                        )
                    
                    # Attendre 30 secondes avant la prochaine vérification
                    time.sleep(30)
                    
                except Exception as e:
                    print(f"Erreur monitoring: {e}")
                    time.sleep(60)  # Attendre plus longtemps en cas d'erreur
        
        self.monitoring_thread = threading.Thread(target=monitoring_loop, daemon=True)
        self.monitoring_thread.start()
    
    def get_system_health(self) -> Dict:
        """Obtenir l'état de santé du système"""
        return {
            "system_metrics": self.system_metrics,
            "problems_count": len(self.problems_detected),
            "recent_problems": self.problems_detected[-5:] if self.problems_detected else [],
            "monitoring_active": self.monitoring_active,
            "thresholds": self.thresholds
        }
    
    def get_recent_logs(self, count: int = 50) -> List[Dict]:
        """Obtenir les logs récents"""
        logs = []
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                for line in lines[-count:]:
                    try:
                        log_entry = json.loads(line.strip())
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        return logs
    
    def get_problems(self, count: int = 20) -> List[Dict]:
        """Obtenir les problèmes récents"""
        problems = []
        try:
            with open(self.problems_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                for line in lines[-count:]:
                    try:
                        problem_entry = json.loads(line.strip())
                        problems.append(problem_entry)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        return problems
    
    def stop_monitoring(self):
        """Arrêter le monitoring système"""
        self.monitoring_active = False
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=5)
        self.log(LogLevel.INFO, "🔧 Monitoring système arrêté")


# Instance globale du logger
_system_logger = None

def get_logger() -> SystemLogger:
    """Obtenir l'instance globale du logger"""
    global _system_logger
    if _system_logger is None:
        _system_logger = SystemLogger()
    return _system_logger


def init_logging(logs_dir: str = "logs") -> SystemLogger:
    """Initialiser le système de logging"""
    global _system_logger
    if _system_logger is None:
        _system_logger = SystemLogger(logs_dir)
    return _system_logger


# Fonctions de convenance
def log_info(message: str, extra_data: Optional[Dict] = None):
    """Log un message info"""
    get_logger().log(LogLevel.INFO, message, extra_data)

def log_warning(message: str, extra_data: Optional[Dict] = None):
    """Log un message warning"""
    get_logger().log(LogLevel.WARNING, message, extra_data)

def log_error(message: str, extra_data: Optional[Dict] = None):
    """Log un message error"""
    get_logger().log(LogLevel.ERROR, message, extra_data)

def log_debug(message: str, extra_data: Optional[Dict] = None):
    """Log un message debug"""
    get_logger().log(LogLevel.DEBUG, message, extra_data)


if __name__ == "__main__":
    # Test du système de logging
    logger = get_logger()
    
    logger.log(LogLevel.INFO, "🧪 Test du système de logging")
    logger.log(LogLevel.WARNING, "⚠️ Test d'un avertissement")
    logger.log(LogLevel.ERROR, "❌ Test d'une erreur FFmpeg crash")
    logger.log(LogLevel.INFO, "✅ Test terminé")
    
    # Afficher l'état de santé
    health = logger.get_system_health()
    print(f"\n🔍 État système: {json.dumps(health, indent=2, ensure_ascii=False)}")
    
    time.sleep(2)
    logger.stop_monitoring()
