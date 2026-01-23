"""
Route publique pour afficher et partager les clips
Accessible sans authentification pour permettre le partage sur les réseaux sociaux
"""

from flask import Blueprint, render_template_string, jsonify, abort
from src.models.user import UserClip
from src.services.social_share_service import social_share_service
import logging

logger = logging.getLogger(__name__)

public_clip_bp = Blueprint('public_clips', __name__)

# Template HTML avec Open Graph metadata et lecteur vidéo embarqué
CLIP_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <!-- Primary Meta Tags -->
    <title>{{ clip.title }} - Spovio</title>
    <meta name="title" content="{{ clip.title }} - Spovio">
    <meta name="description" content="{{ clip.description or 'Regardez ce moment de padel sur Spovio!' }}">
    
    <!-- Open Graph / Facebook -->
    <meta property="og:type" content="video.other">
    <meta property="og:url" content="{{ share_url }}">
    <meta property="og:title" content="{{ clip.title }}">
    <meta property="og:description" content="{{ clip.description or 'Regardez ce clip de padel!' }}">
    <meta property="og:video" content="{{ clip.file_url }}">
    <meta property="og:video:type" content="video/mp4">
    <meta property="og:site_name" content="Spovio">
    {% if clip.thumbnail_url %}
    <meta property="og:image" content="{{ clip.thumbnail_url }}">
    {% endif %}
    
    <!-- Twitter Card -->
    <meta name="twitter:card" content="player">
    <meta name="twitter:title" content="{{ clip.title }}">
    <meta name="twitter:description" content="{{ clip.description or 'Regardez ce clip de padel!' }}">
    <meta name="twitter:player" content="{{ clip.file_url }}">
    {% if clip.thumbnail_url %}
    <meta name="twitter:image" content="{{ clip.thumbnail_url }}">
    {% endif %}
    
    <!-- TikTok -->
    <meta property="tiktok:app_id" content="spovio">
    
    <!-- Favicon -->
    <link rel="icon" href="https://spovio.net/favicon.ico">
    
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        
        .container {
            max-width: 800px;
            width: 100%;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 28px;
            margin-bottom: 10px;
        }
        
        .header p {
            opacity: 0.9;
            font-size: 16px;
        }
        
        .video-container {
            position: relative;
            padding-bottom: 56.25%; /* 16:9 aspect ratio */
            height: 0;
            overflow: hidden;
            background: #000;
        }
        
        .video-container iframe,
        .video-container video {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
        }
        
        .content {
            padding: 30px;
        }
        
        .description {
            font-size: 16px;
            line-height: 1.6;
            color: #333;
            margin-bottom: 20px;
        }
        
        .stats {
            display: flex;
            gap: 20px;
            padding: 20px;
            background: #f7f7f7;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        
        .stat {
            flex: 1;
            text-align: center;
        }
        
        .stat-value {
            font-size: 24px;
            font-weight: bold;
            color: #667eea;
        }
        
        .stat-label {
            font-size: 12px;
            color: #666;
            margin-top: 5px;
        }
        
        .actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        
        .btn {
            flex: 1;
            min-width: 120px;
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.2);
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .btn-secondary {
            background: #f0f0f0;
            color: #333;
        }
        
        .footer {
            text-align: center;
            padding: 20px;
            background: #f7f7f7;
            color: #666;
        }
        
        .footer a {
            color: #667eea;
            text-decoration: none;
        }
        
        @media (max-width: 600px) {
            .header h1 {
                font-size: 22px;
            }
            
            .actions {
                flex-direction: column;
            }
            
            .btn {
                width: 100%;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎾 {{ clip.title }}</h1>
            <p>Partagé depuis Spovio</p>
        </div>
        
        <div class="video-container">
            {% if clip.file_url %}
            <iframe 
                src="{{ clip.file_url }}" 
                frameborder="0" 
                allowfullscreen
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            ></iframe>
            {% endif %}
        </div>
        
        <div class="content">
            {% if clip.description %}
            <div class="description">
                {{ clip.description }}
            </div>
            {% endif %}
            
            <div class="stats">
                <div class="stat">
                    <div class="stat-value">{{ clip.duration or 0 }}s</div>
                    <div class="stat-label">Durée</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{{ clip.share_count or 0 }}</div>
                    <div class="stat-label">Partages</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{{ clip.download_count or 0 }}</div>
                    <div class="stat-label">Téléchargements</div>
                </div>
            </div>
            
            <div class="actions">
                <a href="https://app.spovio.net" class="btn btn-primary">
                    ✨ Créer mes clips
                </a>
                {% if clip.storage_download_url %}
                <a href="{{ clip.storage_download_url }}" class="btn btn-secondary" download>
                    📥 Télécharger
                </a>
                {% endif %}
            </div>
        </div>
        
        <div class="footer">
            <p>Créé avec <a href="https://spovio.net" target="_blank">Spovio</a> - L'avenir du sport vidéo intelligent</p>
        </div>
    </div>
</body>
</html>
"""

@public_clip_bp.route('/clip/<int:clip_id>', methods=['GET'])
def view_public_clip(clip_id):
    """
    Affiche une page publique pour un clip avec métadonnées Open Graph
    Cette route est accessible sans authentification pour permettre le partage
    
    Args:
        clip_id: ID du clip à afficher
    """
    try:
        # Récupérer le clip
        clip = UserClip.query.get(clip_id)
        
        if not clip:
            abort(404, description="Clip not found")
        
        # Vérifier que le clip est prêt
        if clip.status != 'completed':
            abort(404, description="Clip not available yet")
        
        # Générer l'URL de partage
        from flask import request
        share_url = request.url
        
        # Incrémenter le compteur de vues (optionnel)
        # clip.view_count += 1  # Si vous ajoutez ce champ plus tard
        # db.session.commit()
        
        # Rendre le template avec les données du clip
        return render_template_string(
            CLIP_HTML_TEMPLATE,
            clip=clip,
            share_url=share_url
        )
        
    except Exception as e:
        logger.error(f"Error displaying public clip {clip_id}: {e}")
        abort(500, description="Internal server error")


@public_clip_bp.route('/api/clip/<int:clip_id>/metadata', methods=['GET'])
def get_clip_metadata(clip_id):
    """
    API endpoint pour récupérer les métadonnées d'un clip (pour les bots de réseaux sociaux)
    
    Args:
        clip_id: ID du clip
        
    Returns:
        JSON avec les métadonnées Open Graph
    """
    try:
        meta = social_share_service.generate_open_graph_meta(clip_id)
        
        return jsonify({
            'success': True,
            'metadata': meta
        }), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Error getting clip metadata: {e}")
        return jsonify({'error': 'Internal server error'}), 500
