"""
Point d'entrée minimal pour diagnostiquer les problèmes de démarrage
Utilise main_minimal.py au lieu de main.py
"""
import os
import sys
from pathlib import Path

# Configuration du chemin
project_root = Path(__file__).parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Chargement des variables d'environnement
env_file = project_root / '.env'
if env_file.exists():
    print(f"📁 Chargement .env depuis {env_file}")
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())

# Import de la factory MINIMALE
from src.main_minimal import create_app

def main():
    """Fonction principale - Mode Minimal"""
    env = os.environ.get('FLASK_ENV', 'development')
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    
    print(f"🚀 Démarrage Spovio API (MODE MINIMAL)")
    print(f"   Environnement: {env}")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    
    try:
        app = create_app(env)
        print(f"✅ Application créée (MINIMAL)")
        
        app.run(
            host=host,
            port=port,
            debug=False,
            use_reloader=False
        )
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
