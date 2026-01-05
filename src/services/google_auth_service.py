import os
import json
import requests
import logging

# Configuration d'un logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    import jwt  # Pour la vérification des JWT (JSON Web Tokens)
except ImportError:
    logger.error("PyJWT n'est pas installé. Exécutez 'pip install PyJWT'")
    # Utiliser un module de remplacement minimal
    class DummyJWT:
        @staticmethod
        def get_unverified_header(token):
            logger.error("PyJWT n'est pas disponible, impossible de vérifier le token")
            return {}
        @staticmethod
        def decode(*args, **kwargs):
            logger.error("PyJWT n'est pas disponible, impossible de décoder le token")
            return {}
    jwt = DummyJWT()

# Configuration Google OAuth
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', 'YOUR_GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', 'YOUR_GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', 'http://localhost:5000/api/auth/google/callback')
BACKEND_URL = os.environ.get('BACKEND_URL', 'http://localhost:5000')

# Vérifier la configuration
if GOOGLE_CLIENT_ID == 'YOUR_GOOGLE_CLIENT_ID':
    logger.warning("⚠️ GOOGLE_CLIENT_ID n'est pas configuré! L'authentification Google ne fonctionnera pas.")
    logger.warning("⚠️ Exécutez setup_google_auth.ps1 après avoir configuré vos identifiants Google OAuth.")
    logger.warning("⚠️ Consultez le fichier GOOGLE_OAUTH_SETUP.md pour les instructions détaillées.")

def verify_google_token(token):
    """Vérifie un token Google et retourne les infos utilisateur"""
    try:
        if GOOGLE_CLIENT_ID == 'YOUR_GOOGLE_CLIENT_ID':
            logger.error("❌ GOOGLE_CLIENT_ID non configuré - Impossible de vérifier le token")
            return None
            
        logger.info(f"🔍 Tentative de vérification du token Google...")
        
        # Récupérer les clés publiques de Google
        keys_response = requests.get('https://www.googleapis.com/oauth2/v1/certs')
        keys = keys_response.json()
        
        # Décoder le header du token pour obtenir le kid
        header = jwt.get_unverified_header(token)
        kid = header.get('kid')
        
        if not kid or kid not in keys:
            logger.error(f"❌ 'kid' invalide ou manquant dans le token: {kid}")
            return None
            
        # Vérifier le token avec la clé correspondante
        public_key = keys[kid]
        
        # Décoder et vérifier le token
        payload = jwt.decode(
            token,
            public_key,
            algorithms=['RS256'],
            audience=GOOGLE_CLIENT_ID,
            options={"verify_exp": True}
        )
        
        # Vérifier que le token est destiné à votre application
        if payload['aud'] != GOOGLE_CLIENT_ID:
            raise ValueError('Client ID incorrect')
        
        # Retourner les informations d'utilisateur
        return {
            'email': payload['email'],
            'name': payload.get('name', ''),
            'picture': payload.get('picture', ''),
            'google_id': payload['sub'],
            'email_verified': payload.get('email_verified', False)
        }
        
    except Exception as e:
        # Token invalide
        print(f"Erreur de vérification du token Google: {e}")
        return None

def get_google_user_info(access_token):
    """Récupère les informations de l'utilisateur Google via l'API"""
    try:
        logger.info(f"🔍 Récupération des informations utilisateur Google...")
        userinfo_endpoint = "https://www.googleapis.com/oauth2/v3/userinfo"
        headers = {'Authorization': f'Bearer {access_token}'}
        
        response = requests.get(userinfo_endpoint, headers=headers)
        if response.status_code == 200:
            logger.info("✅ Informations utilisateur Google récupérées avec succès")
            return response.json()
        else:
            logger.error(f"❌ Erreur lors de la récupération des infos utilisateur: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'appel à l'API Google: {str(e)}")
        return None

def get_google_tokens(code):
    """Échange le code d'autorisation contre des tokens"""
    try:
        if GOOGLE_CLIENT_ID == 'YOUR_GOOGLE_CLIENT_ID' or GOOGLE_CLIENT_SECRET == 'YOUR_GOOGLE_CLIENT_SECRET':
            logger.error("❌ Google OAuth non configuré - ID client ou secret manquant")
            return None
            
        logger.info(f"🔄 Échange du code d'autorisation contre des tokens...")
        token_endpoint = "https://oauth2.googleapis.com/token"
        
        data = {
            'code': code,
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'redirect_uri': GOOGLE_REDIRECT_URI,
            'grant_type': 'authorization_code'
        }
        
        logger.debug(f"📤 Paramètres de requête token: client_id={GOOGLE_CLIENT_ID}, redirect_uri={GOOGLE_REDIRECT_URI}")
        
        response = requests.post(token_endpoint, data=data)
        if response.status_code == 200:
            logger.info("✅ Tokens Google obtenus avec succès")
            return response.json()
        else:
            logger.error(f"❌ Erreur lors de l'échange du code: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'échange du code: {str(e)}")
        return None

# Assurez-vous d'installer la bibliothèque PyJWT
# pip install PyJWT

if __name__ == "__main__":
    import app  # Remplacez ceci par le point d'entrée de votre application
    os.system('flask db upgrade')
