# src/tasks/__init__.py

"""
Tâches asynchrones Celery pour PadelVar
"""

from .video_processing import *
from .notification_tasks import *
from .maintenance_tasks import *
from .payment_tasks import *