"""
Service pour générer des liens de partage sur les réseaux sociaux
Supporte Instagram, TikTok, WhatsApp, Facebook
"""

import logging
from typing import Dict
from urllib.parse import quote
from src.models.database import db
from src.models.user import UserClip

logger = logging.getLogger(__name__)


class SocialShareService:
    """Service pour générer des liens de partage social"""
    
    def __init__(self, app_base_url: str = "https://padelvar.com"):
        self.app_base_url = app_base_url.rstrip('/')
    
    def generate_share_links(self, clip_id: int) -> Dict[str, str]:
        """
        Génère les liens de partage pour toutes les plateformes
        
        Args:
            clip_id: ID du clip à partager
        
        Returns:
            dict: Dictionnaire avec les URLs de partage par plateforme
        """
        clip = UserClip.query.get(clip_id)
        
        if not clip:
            raise ValueError("Clip not found")
        
        if clip.status != 'completed':
            raise ValueError("Clip is not ready for sharing")
        
        # URL de la page de visualisation du clip
        clip_page_url = f"{self.app_base_url}/clips/{clip_id}"
        
        # URL directe de la vidéo
        video_url = clip.file_url
        
        # Préparer les métadonnées
        title = clip.title or "Mon clip Padel"
        description = clip.description or f"Regardez ce moment de {clip.duration}s de mon match de padel !"
        
        # Générer les liens pour chaque plateforme
        links = {
            'direct_url': video_url,
            'page_url': clip_page_url,
            'whatsapp': self._generate_whatsapp_link(clip_page_url, title),
            'facebook': self._generate_facebook_link(clip_page_url),
            'instagram': clip_page_url,  # Instagram ne permet pas de lien direct
            'tiktok': video_url,  # TikTok nécessite téléchargement
            'twitter': self._generate_twitter_link(clip_page_url, title),
            'email': self._generate_email_link(clip_page_url, title, description),
            'download': video_url
        }
        
        # Incrémenter le compteur de partages
        # (on ne l'incrémente qu'au moment du partage effectif)
        
        return links
    
    def _generate_whatsapp_link(self, url: str, title: str) -> str:
        """Génère un lien de partage WhatsApp"""
        text = f"{title} - {url}"
        encoded_text = quote(text)
        return f"https://wa.me/?text={encoded_text}"
    
    def _generate_facebook_link(self, url: str) -> str:
        """Génère un lien de partage Facebook"""
        encoded_url = quote(url)
        return f"https://www.facebook.com/sharer/sharer.php?u={encoded_url}"
    
    def _generate_twitter_link(self, url: str, title: str) -> str:
        """Génère un lien de partage Twitter/X"""
        text = quote(title)
        encoded_url = quote(url)
        return f"https://twitter.com/intent/tweet?text={text}&url={encoded_url}"
    
    def _generate_email_link(self, url: str, title: str, description: str) -> str:
        """Génère un lien mailto pour partage par email"""
        subject = quote(f"Regardez mon clip: {title}")
        body = quote(f"{description}\n\nVoir la vidéo: {url}")
        return f"mailto:?subject={subject}&body={body}"
    
    def track_share(self, clip_id: int, platform: str):
        """
        Enregistre un partage
        
        Args:
            clip_id: ID du clip partagé
            platform: Plateforme (whatsapp, facebook, etc.)
        """
        clip = UserClip.query.get(clip_id)
        
        if clip:
            clip.share_count += 1
            db.session.commit()
            logger.info(f"Clip {clip_id} shared on {platform}")
    
    def track_download(self, clip_id: int):
        """
        Enregistre un téléchargement
        
        Args:
            clip_id: ID du clip téléchargé
        """
        clip = UserClip.query.get(clip_id)
        
        if clip:
            clip.download_count += 1
            db.session.commit()
            logger.info(f"Clip {clip_id} downloaded")
    
    def generate_open_graph_meta(self, clip_id: int) -> Dict[str, str]:
        """
        Génère les meta tags Open Graph pour le partage
        
        Args:
            clip_id: ID du clip
        
        Returns:
            dict: Meta tags Open Graph
        """
        clip = UserClip.query.get(clip_id)
        
        if not clip:
            raise ValueError("Clip not found")
        
        meta = {
            'og:title': clip.title,
            'og:description': clip.description or f"Clip de {clip.duration}s - MySmash",
            'og:type': 'video.other',
            'og:url': f"{self.app_base_url}/clips/{clip_id}",
            'og:video': clip.file_url,
            'og:video:type': 'video/mp4',
            'og:site_name': 'MySmash',
        }
        
        if clip.thumbnail_url:
            meta['og:image'] = clip.thumbnail_url
        
        # Twitter Card
        meta.update({
            'twitter:card': 'player',
            'twitter:title': clip.title,
            'twitter:description': clip.description or f"Clip de {clip.duration}s",
            'twitter:player': clip.file_url,
        })
        
        if clip.thumbnail_url:
            meta['twitter:image'] = clip.thumbnail_url
        
        return meta
    
    def generate_instagram_instructions(self) -> Dict[str, str]:
        """
        Génère les instructions pour partager sur Instagram
        
        Returns:
            dict: Instructions de partage
        """
        return {
            'method': 'manual',
            'steps': [
                '1. Téléchargez la vidéo sur votre appareil',
                '2. Ouvrez Instagram',
                '3. Créez une nouvelle Story ou un Reel',
                '4. Sélectionnez la vidéo téléchargée',
                '5. Ajoutez vos filtres et partagez !'
            ],
            'note': 'Instagram ne permet pas le partage direct depuis le web. '
                   'Vous devez télécharger et uploader manuellement.'
        }
    
    def generate_tiktok_instructions(self) -> Dict[str, str]:
        """
        Génère les instructions pour partager sur TikTok
        
        Returns:
            dict: Instructions de partage
        """
        return {
            'method': 'manual',
            'steps': [
                '1. Téléchargez la vidéo sur votre appareil mobile',
                '2. Ouvrez l\'application TikTok',
                '3. Appuyez sur le bouton "+" pour créer',
                '4. Sélectionnez "Upload"',
                '5. Choisissez votre vidéo',
                '6. Ajoutez musique, effets et description',
                '7. Publiez !'
            ],
            'tip': 'Pour de meilleurs résultats, utilisez un format vertical (9:16)'
        }


# Instance globale
social_share_service = SocialShareService()
