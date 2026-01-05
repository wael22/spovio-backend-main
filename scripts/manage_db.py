#!/usr/bin/env python3
"""
Script de gestion de la base de données PadelVar
Gère les migrations, l'initialisation, et les opérations de maintenance
"""
import os
import sys
import click
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate, init, migrate, upgrade, downgrade
import subprocess

# Ajouter le chemin du projet
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.config import Config
from src.models.database import db
from src.models.user import User, UserStatus, Transaction, TransactionStatus, Notification, NotificationType
from src.models.recording import RecordingSession

# Configuration Flask minimale pour les migrations
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    db.init_app(app)
    migrate = Migrate(app, db)
    
    return app

@click.group()
def cli():
    """Commandes de gestion de la base de données"""
    pass

@cli.command()
@click.option('--env', default='development', help='Environnement (development/production/testing)')
def init_db(env):
    """Initialise la base de données et les migrations"""
    os.environ['FLASK_ENV'] = env
    
    app = create_app()
    with app.app_context():
        # Vérifier si migrations existe
        migrations_dir = os.path.join(os.path.dirname(__file__), '..', 'migrations')
        
        if not os.path.exists(migrations_dir):
            click.echo("Initialisation des migrations...")
            init()
        
        # Créer les tables si elles n'existent pas
        db.create_all()
        click.echo(f"✅ Base de données initialisée pour l'environnement: {env}")
        
        # Afficher les informations de connexion
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', 'Non configuré')
        click.echo(f"📍 URL de base de données: {db_uri}")

@cli.command()
@click.option('--message', '-m', required=True, help='Message de la migration')
@click.option('--autogenerate/--no-autogenerate', default=True, help='Génération automatique')
def create_migration(message, autogenerate):
    """Crée une nouvelle migration"""
    app = create_app()
    with app.app_context():
        if autogenerate:
            migrate(message=message)
        else:
            # Migration manuelle
            revision_id = subprocess.check_output([
                'alembic', 'revision', '--message', message
            ]).decode().strip()
        
        click.echo(f"✅ Migration créée: {message}")

@cli.command()
@click.option('--target', default='head', help='Version cible de la migration')
def apply_migrations(target):
    """Applique les migrations à la base de données"""
    app = create_app()
    with app.app_context():
        try:
            upgrade(revision=target)
            click.echo("✅ Migrations appliquées avec succès")
        except Exception as e:
            click.echo(f"❌ Erreur lors de l'application des migrations: {e}")
            sys.exit(1)

@cli.command()
@click.option('--target', required=True, help='Version cible pour le rollback')
def rollback(target):
    """Effectue un rollback vers une version antérieure"""
    app = create_app()
    with app.app_context():
        try:
            downgrade(revision=target)
            click.echo(f"✅ Rollback vers {target} effectué avec succès")
        except Exception as e:
            click.echo(f"❌ Erreur lors du rollback: {e}")
            sys.exit(1)

@cli.command()
def check_db():
    """Vérifie l'état de la base de données"""
    app = create_app()
    with app.app_context():
        try:
            # Tester la connexion
            result = db.engine.execute('SELECT 1')
            click.echo("✅ Connexion à la base de données OK")
            
            # Vérifier les tables principales
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            
            expected_tables = [
                'users', 'courts', 'matches', 'recordings', 
                'transactions', 'notifications'
            ]
            
            click.echo("\n📊 Tables existantes:")
            for table in tables:
                status = "✅" if table in expected_tables else "ℹ️"
                click.echo(f"  {status} {table}")
            
            # Vérifier les tables manquantes
            missing_tables = set(expected_tables) - set(tables)
            if missing_tables:
                click.echo(f"\n⚠️  Tables manquantes: {', '.join(missing_tables)}")
                click.echo("   Exécutez 'python scripts/manage_db.py apply-migrations' pour les créer")
            
        except Exception as e:
            click.echo(f"❌ Erreur de connexion: {e}")
            sys.exit(1)

@cli.command()
def create_admin():
    """Crée un utilisateur administrateur"""
    app = create_app()
    with app.app_context():
        # Demander les informations
        email = click.prompt('Email administrateur')
        password = click.prompt('Mot de passe', hide_input=True)
        confirm_password = click.prompt('Confirmer le mot de passe', hide_input=True)
        
        if password != confirm_password:
            click.echo("❌ Les mots de passe ne correspondent pas")
            sys.exit(1)
        
        # Vérifier si l'utilisateur existe
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            click.echo("❌ Un utilisateur avec cet email existe déjà")
            sys.exit(1)
        
        # Créer l'administrateur
        try:
            admin = User(
                email=email,
                name="Administrateur",
                role="admin",
                status=UserStatus.ACTIVE
            )
            admin.set_password(password)
            
            db.session.add(admin)
            db.session.commit()
            
            click.echo(f"✅ Administrateur créé: {email}")
            
        except Exception as e:
            click.echo(f"❌ Erreur lors de la création: {e}")
            db.session.rollback()
            sys.exit(1)

@cli.command()
def reset_db():
    """Remet à zéro la base de données (ATTENTION: supprime toutes les données)"""
    if not click.confirm('⚠️  ATTENTION: Cette opération supprimera toutes les données. Continuer?'):
        click.echo("Opération annulée")
        return
    
    app = create_app()
    with app.app_context():
        try:
            db.drop_all()
            db.create_all()
            click.echo("✅ Base de données remise à zéro")
        except Exception as e:
            click.echo(f"❌ Erreur lors de la remise à zéro: {e}")
            sys.exit(1)

@cli.command()
def show_status():
    """Affiche le statut détaillé de la base de données"""
    app = create_app()
    with app.app_context():
        try:
            # Informations de base
            click.echo("📊 Statut de la base de données PadelVar\n")
            
            db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', 'Non configuré')
            env = os.environ.get('FLASK_ENV', 'development')
            
            click.echo(f"🌍 Environnement: {env}")
            click.echo(f"📍 Base de données: {db_uri}")
            
            # Statistiques des tables
            user_count = User.query.count()
            recording_count = RecordingSession.query.count()
            
            if 'Transaction' in globals():
                transaction_count = Transaction.query.count()
            else:
                transaction_count = "Table non créée"
                
            if 'Notification' in globals():
                notification_count = Notification.query.count()
            else:
                notification_count = "Table non créée"
            
            click.echo(f"\n📈 Statistiques:")
            click.echo(f"  👥 Utilisateurs: {user_count}")
            click.echo(f"  🎥 Sessions d'enregistrement: {recording_count}")
            click.echo(f"  💳 Transactions: {transaction_count}")
            click.echo(f"  🔔 Notifications: {notification_count}")
            
        except Exception as e:
            click.echo(f"❌ Erreur lors de la récupération du statut: {e}")
            sys.exit(1)

if __name__ == '__main__':
    cli()