#!/usr/bin/env python3
"""
Script de validation de la configuration PadelVar
Vérifie que toutes les variables d'environnement requises sont définies
"""
import os
import sys
import re
from typing import List, Dict, Tuple

def check_required_vars() -> List[str]:
    """Vérifie les variables d'environnement requises"""
    required_vars = [
        'SECRET_KEY',
        'JWT_SECRET_KEY', 
        'DB_PASSWORD',
        'REDIS_PASSWORD',
        'STRIPE_SECRET_KEY',
        'BUNNY_API_KEY'
    ]
    
    missing = []
    for var in required_vars:
        if not os.environ.get(var):
            missing.append(var)
    
    return missing

def check_password_strength() -> List[str]:
    """Vérifie la force des mots de passe"""
    weak_passwords = []
    
    password_vars = {
        'SECRET_KEY': 32,
        'JWT_SECRET_KEY': 32,
        'DB_PASSWORD': 12,
        'REDIS_PASSWORD': 12,
        'GRAFANA_ADMIN_PASSWORD': 12
    }
    
    default_patterns = [
        'CHANGEME',
        'password',
        '123456',
        'admin'
    ]
    
    for var, min_length in password_vars.items():
        value = os.environ.get(var, '')
        
        if len(value) < min_length:
            weak_passwords.append(f"{var}: trop court (< {min_length} chars)")
        
        for pattern in default_patterns:
            if pattern.lower() in value.lower():
                weak_passwords.append(f"{var}: contient un motif par défaut ({pattern})")
    
    return weak_passwords

def check_stripe_config() -> List[str]:
    """Vérifie la configuration Stripe"""
    issues = []
    
    publishable = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
    secret = os.environ.get('STRIPE_SECRET_KEY', '')
    webhook = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
    
    # Vérifier format des clés
    if publishable and not (publishable.startswith('pk_test_') or publishable.startswith('pk_live_')):
        issues.append("STRIPE_PUBLISHABLE_KEY: format invalide")
    
    if secret and not (secret.startswith('sk_test_') or secret.startswith('sk_live_')):
        issues.append("STRIPE_SECRET_KEY: format invalide")
    
    if webhook and not webhook.startswith('whsec_'):
        issues.append("STRIPE_WEBHOOK_SECRET: format invalide")
    
    # Vérifier cohérence test/live
    if publishable and secret:
        pub_mode = 'live' if publishable.startswith('pk_live_') else 'test'
        sec_mode = 'live' if secret.startswith('sk_live_') else 'test'
        
        if pub_mode != sec_mode:
            issues.append("Clés Stripe incohérentes (test/live)")
    
    return issues

def check_database_config() -> List[str]:
    """Vérifie la configuration base de données"""
    issues = []
    
    env = os.environ.get('FLASK_ENV', 'development')
    
    if env == 'production':
        # En production, PostgreSQL requis
        db_host = os.environ.get('DB_HOST')
        if not db_host or db_host == 'localhost':
            issues.append("DB_HOST requis en production (pas localhost)")
        
        if not os.environ.get('DB_NAME'):
            issues.append("DB_NAME requis en production")
        
        if not os.environ.get('DB_USER'):
            issues.append("DB_USER requis en production")
    
    return issues

def check_redis_config() -> List[str]:
    """Vérifie la configuration Redis"""
    issues = []
    
    redis_host = os.environ.get('REDIS_HOST')
    redis_port = os.environ.get('REDIS_PORT', '6379')
    
    if not redis_host:
        issues.append("REDIS_HOST requis")
    
    try:
        port = int(redis_port)
        if port < 1 or port > 65535:
            issues.append("REDIS_PORT invalide")
    except ValueError:
        issues.append("REDIS_PORT doit être un nombre")
    
    return issues

def check_ports_conflicts() -> List[str]:
    """Vérifie les conflits de ports"""
    issues = []
    
    ports = {
        'APP_PORT': os.environ.get('APP_PORT', '5000'),
        'POSTGRES_PORT': os.environ.get('POSTGRES_PORT', '5432'),
        'REDIS_PORT': os.environ.get('REDIS_PORT', '6379'),
        'PROMETHEUS_PORT': os.environ.get('PROMETHEUS_PORT', '9090'),
        'GRAFANA_PORT': os.environ.get('GRAFANA_PORT', '3000')
    }
    
    used_ports = []
    for name, port in ports.items():
        try:
            port_num = int(port)
            if port_num in used_ports:
                issues.append(f"Conflit de port {port_num} ({name})")
            used_ports.append(port_num)
        except ValueError:
            issues.append(f"{name}: port invalide ({port})")
    
    return issues

def check_production_readiness() -> List[str]:
    """Vérifie si la config est prête pour production"""
    issues = []
    
    env = os.environ.get('FLASK_ENV', 'development')
    
    if env == 'production':
        # Vérifications spécifiques production
        if os.environ.get('FLASK_DEBUG', '').lower() == 'true':
            issues.append("FLASK_DEBUG doit être false en production")
        
        if not os.environ.get('DOMAIN_NAME'):
            issues.append("DOMAIN_NAME requis en production")
        
        # Vérifier clés Stripe production
        stripe_key = os.environ.get('STRIPE_SECRET_KEY', '')
        if stripe_key and stripe_key.startswith('sk_test_'):
            issues.append("Clés Stripe de test en production")
    
    return issues

def print_summary(results: Dict[str, List[str]]) -> None:
    """Affiche le résumé des vérifications"""
    print("=" * 60)
    print("🔍 VALIDATION CONFIGURATION PADELVAR v2.0")
    print("=" * 60)
    
    total_issues = sum(len(issues) for issues in results.values())
    
    if total_issues == 0:
        print("✅ Configuration valide ! Aucun problème détecté.")
        print("")
        print("🚀 Votre PadelVar est prêt pour le déploiement.")
        return
    
    print(f"❌ {total_issues} problème(s) détecté(s) :")
    print("")
    
    for category, issues in results.items():
        if issues:
            print(f"🔴 {category.upper()}:")
            for issue in issues:
                print(f"   • {issue}")
            print("")
    
    print("🔧 ACTIONS REQUISES:")
    print("   1. Corrigez les problèmes listés ci-dessus")
    print("   2. Relancez: python scripts/validate_config.py")
    print("   3. Consultez .env.example pour les formats attendus")
    print("")

def main():
    """Fonction principale"""
    print("Chargement de la configuration...")
    
    # Charger .env si présent
    env_file = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(env_file):
        from dotenv import load_dotenv
        load_dotenv(env_file)
        print(f"✓ Fichier .env chargé: {env_file}")
    else:
        print("⚠️  Fichier .env non trouvé, utilisation variables système")
    
    print("")
    
    # Exécuter toutes les vérifications
    results = {
        'variables_manquantes': check_required_vars(),
        'mots_de_passe_faibles': check_password_strength(),
        'configuration_stripe': check_stripe_config(),
        'configuration_database': check_database_config(),
        'configuration_redis': check_redis_config(),
        'conflits_ports': check_ports_conflicts(),
        'production_readiness': check_production_readiness()
    }
    
    # Afficher résumé
    print_summary(results)
    
    # Code de sortie
    total_issues = sum(len(issues) for issues in results.values())
    sys.exit(1 if total_issues > 0 else 0)

if __name__ == '__main__':
    main()