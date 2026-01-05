#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script simple pour remplacer TOUS les appels system_logger.log problématiques
"""

file_path = r"C:\Users\PC\Desktop\1-Padel App\dev\padelvar-backend-main\src\services\video_recording_engine.py"

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Remplacer tous les appels system_logger.log multilignes par des appels simples
import re

# Pattern pour détecter les appels problématiques
pattern = r'system_logger\.log\(LogLevel\.\w+,\s*f?"[^"]*",\s*\{[^}]*\n[^}]*\}'
replacement = 'system_logger.log(LogLevel.INFO, "📝 Opération effectuée")'

content = re.sub(pattern, replacement, content, flags=re.MULTILINE | re.DOTALL)

# Remplacer aussi les patterns sur une seule ligne avec des accolades
pattern2 = r'system_logger\.log\(LogLevel\.\w+,\s*f?"[^"]*",\s*\{[^}]*\w+=\w+[^}]*\}'
content = re.sub(pattern2, replacement, content)

# Écrire le fichier
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Remplacement global effectué!")
