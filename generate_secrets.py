"""
Script pour générer les secrets nécessaires pour le déploiement en production
Exécutez: python generate_secrets.py
"""
import secrets

def generate_secrets():
    """Génère tous les secrets nécessaires pour la production"""
    
    print("=" * 60)
    print("🔐 GÉNÉRATION DES SECRETS POUR RENDER")
    print("=" * 60)
    print()
    
    # Générer SECRET_KEY
    secret_key = secrets.token_urlsafe(32)
    print("🔑 SECRET_KEY (Flask):")
    print(f"   {secret_key}")
    print()
    
    # Générer JWT_SECRET_KEY
    jwt_secret = secrets.token_urlsafe(32)
    print("🔑 JWT_SECRET_KEY:")
    print(f"   {jwt_secret}")
    print()
    
    # Générer un chemin super admin aléatoire
    admin_path = f"/super-admin-{secrets.token_urlsafe(8)}"
    print("🔐 SUPER_ADMIN_LOGIN_PATH (changez le chemin par défaut):")
    print(f"   {admin_path}")
    print()
    
    # Générer un mot de passe admin sécurisé
    admin_password = secrets.token_urlsafe(16)
    print("🔐 DEFAULT_ADMIN_PASSWORD (mot de passe temporaire):")
    print(f"   {admin_password}")
    print()
    
    print("=" * 60)
    print("📋 VARIABLES À AJOUTER DANS RENDER")
    print("=" * 60)
    print()
    print("Copiez ces variables dans: Environment → Environment Variables")
    print()
    
    env_vars = f"""SECRET_KEY={secret_key}
JWT_SECRET_KEY={jwt_secret}
SUPER_ADMIN_LOGIN_PATH={admin_path}
DEFAULT_ADMIN_PASSWORD={admin_password}"""
    
    print(env_vars)
    print()
    
    # Sauvegarder dans un fichier
    with open('.secrets.txt', 'w') as f:
        f.write("=" * 60 + "\n")
        f.write("SECRETS GÉNÉRÉS POUR RENDER - CONFIDENTIEL!\n")
        f.write("NE PAS COMMITER CE FICHIER!\n")
        f.write("=" * 60 + "\n\n")
        f.write(env_vars)
        f.write("\n\n")
        f.write("=" * 60 + "\n")
        f.write("IMPORTANT:\n")
        f.write("- Ajoutez ces variables dans Render Dashboard\n")
        f.write("- Conservez ce fichier en lieu sûr (gestionnaire de mots de passe)\n")
        f.write("- SUPPRIMEZ ce fichier après configuration!\n")
        f.write("=" * 60 + "\n")
    
    print("✅ Secrets sauvegardés dans '.secrets.txt'")
    print("⚠️  IMPORTANT: Ne committez PAS ce fichier sur Git!")
    print("⚠️  Ajoutez '.secrets.txt' au .gitignore")
    print()
    print("=" * 60)

if __name__ == '__main__':
    generate_secrets()
