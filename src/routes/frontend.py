from flask import Blueprint, send_from_directory, current_app
import os

frontend_bp = Blueprint('frontend', __name__)

@frontend_bp.route('/')
@frontend_bp.route('/<path:path>')
def serve_frontend(path=''):
    """Servir les fichiers du frontend React"""
    static_folder = os.path.join(current_app.root_path, 'static')
    
    # Si le chemin correspond à un fichier statique, le servir directement
    if path and os.path.exists(os.path.join(static_folder, path)):
        return send_from_directory(static_folder, path)
    
    # Sinon, servir index.html pour le routage côté client
    return send_from_directory(static_folder, 'index.html')

