#!/usr/bin/env python3
"""
Script pour uploader des vidéos vers Bunny CDN
Utilise les paramètres de connexion FTP pour transférer des vidéos depuis le stockage local vers Bunny CDN.
"""

import os
import sys
import ftplib
import logging
import argparse
from pathlib import Path

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Paramètres FTP Bunny CDN
FTP_HOST = "storage.bunnycdn.com"
FTP_PORT = 21
FTP_USER = "padelvar"  # Nom d'utilisateur affiché dans l'interface Bunny CDN
FTP_PASSWORD = "a93a3ae4-8560-4086-8d4de4d636d5-f0b9-4db5"  # Mot de passe affiché dans l'interface Bunny CDN

def upload_file_to_bunny(local_path, remote_filename=None):
    """Upload un fichier vers Bunny CDN via FTP."""
    try:
        # Si le nom de fichier distant n'est pas spécifié, utiliser le nom du fichier local
        if remote_filename is None:
            remote_filename = os.path.basename(local_path)
        
        # Établir la connexion FTP
        logger.info(f"Connexion à {FTP_HOST}...")
        with ftplib.FTP(FTP_HOST) as ftp:
            # Login
            ftp.login(user=FTP_USER, passwd=FTP_PASSWORD)
            logger.info("Connexion établie!")
            
            # Ouvrir le fichier local et l'uploader
            with open(local_path, 'rb') as file:
                logger.info(f"Uploading {local_path} vers {remote_filename}...")
                ftp.storbinary(f'STOR {remote_filename}', file)
            
            logger.info(f"Upload terminé avec succès! Le fichier est disponible à: https://storage.bunnycdn.com/{FTP_USER}/{remote_filename}")
            return True
            
    except ftplib.all_errors as e:
        logger.error(f"Erreur FTP: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        return False

def upload_directory_to_bunny(local_dir, remote_dir=None):
    """Upload tous les fichiers d'un dossier vers Bunny CDN."""
    try:
        # Vérifier que le dossier existe
        if not os.path.isdir(local_dir):
            logger.error(f"Le dossier {local_dir} n'existe pas!")
            return False
        
        # Obtenir la liste des fichiers du dossier
        files = [f for f in os.listdir(local_dir) if os.path.isfile(os.path.join(local_dir, f))]
        
        if not files:
            logger.warning(f"Aucun fichier trouvé dans {local_dir}")
            return True
        
        # Upload chaque fichier
        success_count = 0
        for file in files:
            local_path = os.path.join(local_dir, file)
            
            # Déterminer le nom du fichier distant
            if remote_dir:
                remote_filename = f"{remote_dir}/{file}"
            else:
                remote_filename = file
                
            # Upload le fichier
            if upload_file_to_bunny(local_path, remote_filename):
                success_count += 1
            
        logger.info(f"Upload terminé: {success_count}/{len(files)} fichiers uploadés avec succès")
        return success_count == len(files)
        
    except Exception as e:
        logger.error(f"Erreur lors de l'upload du dossier: {str(e)}")
        return False

def main():
    """Fonction principale avec parsing des arguments."""
    parser = argparse.ArgumentParser(description='Upload des fichiers vers Bunny CDN via FTP')
    parser.add_argument('--file', help='Fichier local à uploader')
    parser.add_argument('--directory', help='Dossier local à uploader (tous les fichiers)')
    parser.add_argument('--remote-name', help='Nom du fichier distant (si différent du nom local)')
    parser.add_argument('--remote-dir', help='Dossier distant pour upload de dossier')
    
    args = parser.parse_args()
    
    if args.file:
        if not os.path.isfile(args.file):
            logger.error(f"Le fichier {args.file} n'existe pas!")
            return 1
        
        success = upload_file_to_bunny(args.file, args.remote_name)
        return 0 if success else 1
        
    elif args.directory:
        if not os.path.isdir(args.directory):
            logger.error(f"Le dossier {args.directory} n'existe pas!")
            return 1
            
        success = upload_directory_to_bunny(args.directory, args.remote_dir)
        return 0 if success else 1
        
    else:
        parser.print_help()
        return 1

if __name__ == "__main__":
    sys.exit(main())
