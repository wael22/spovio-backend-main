# Utiliser une image Python officielle légère
FROM python:3.10-slim

# Définir le répertoire de travail
WORKDIR /app

# Installer les dépendances système nécessaires pour FFmpeg et OpenCV
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copier les fichiers de dépendances
COPY requirements.txt requirements_video.txt ./

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r requirements_video.txt

# Copier tout le code de l'application
COPY . .

# Créer les dossiers nécessaires pour le stockage temporaire
RUN mkdir -p /tmp/uploads /tmp/recordings /tmp/temp_recordings && \
    chmod 777 /tmp/uploads /tmp/recordings /tmp/temp_recordings

# Exposer le port (Render/OVH utilise souvent une variable d'env, défaut 5000)
ENV PORT=5000
EXPOSE 5000

# Commande de démarrage avec Python directement (pour diagnostics)
# CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "3", "--threads", "4", "--timeout", "120", "wsgi:application"]
CMD ["python", "wsgi.py"]
