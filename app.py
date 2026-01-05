"""
Point d'entrée principal pour l'application MySmash
Lance le serveur de développement Flask
"""
import os
import sys
from pathlib import Path

# Configuration du chemin pour permettre l'importation du package src
project_root = Path(__file__).parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Chargement des variables d'environnement depuis .env si le fichier existe
env_file = project_root / '.env'
if env_file.exists():
    print(f"📁 Chargement des variables d'environnement depuis {env_file}")
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())

# Import de la factory d'application
from src.main import create_app

def main():
    """Fonction principale pour lancer l'application"""
    
    # Récupération de la configuration depuis les variables d'environnement
    env = os.environ.get('FLASK_ENV', 'development')
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'True').lower() == 'true'
    
    print(f"🚀 Démarrage de MySmash API")
    print(f"   Environnement: {env}")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   Debug: {debug}")
    print(f"   Dossier projet: {project_root}")
    
    # Création de l'application
    try:
        app = create_app(env)
        print(f"✅ Application créée avec succès")
        
        # Lancement du serveur
        app.run(
            host=host,
            port=port,
            debug=debug,
            use_reloader=False  # Rechargement automatique désactivé pour éviter les crashs Windows
        )
        
    except Exception as e:
        print(f"❌ Erreur lors du démarrage de l'application: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()

