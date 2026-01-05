# --- ROUTES DE CONFIGURATION SYSTÈME ---

@admin_bp.route("/config", methods=["GET"])
def get_system_config():
    """Récupère toutes les configurations système"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        configs = SystemConfiguration.query.all()
        
        # Grouper par type
        configs_by_type = {}
        for config in configs:
            config_type = config.config_type.value
            if config_type not in configs_by_type:
                configs_by_type[config_type] = []
            
            # Masquer les valeurs sensibles par défaut
            configs_by_type[config_type].append(
                config.to_dict(include_value=True, decrypt=False, mask_sensitive=True)
            )
        
        return jsonify({
            "configs": configs_by_type,
            "total": len(configs)
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur récupération config: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/config/bunny-cdn", methods=["GET"])
def get_bunny_cdn_config():
    """Récupère la configuration Bunny CDN"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        config = SystemConfiguration.get_bunny_cdn_config()
        
        # Masquer l'API key
        if config.get('api_key'):
            config['api_key_masked'] = '********'
            config.pop('api_key')  # Ne pas envoyer la clé complète
        
        return jsonify(config), 200
        
    except Exception as e:
        logger.error(f"Erreur récupération Bunny config: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/config/bunny-cdn", methods=["PUT"])
def update_bunny_cdn_config():
    """Met à jour la configuration Bunny CDN"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        data = request.get_json()
        user_id = session.get("user_id")
        
        # Validation
        api_key = data.get('api_key')
        library_id = data.get('library_id')
        cdn_hostname = data.get('cdn_hostname')
        storage_zone = data.get('storage_zone')
        
        if not all([api_key, library_id, cdn_hostname]):
            return jsonify({"error": "Tous les champs obligatoires doivent être remplis"}), 400
        
        # Mettre à jour la configuration
        SystemConfiguration.set_bunny_cdn_config(
            api_key=api_key,
            library_id=library_id,
            cdn_hostname=cdn_hostname,
            storage_zone=storage_zone,
            updated_by=user_id
        )
        
        logger.info(f"Configuration Bunny CDN mise à jour par utilisateur {user_id}")
        
        return jsonify({
            "message": "Configuration Bunny CDN mise à jour avec succès",
            "config": {
                "library_id": library_id,
                "cdn_hostname": cdn_hostname,
                "storage_zone": storage_zone
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur mise à jour Bunny config: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/config/test-bunny", methods=["POST"])
def test_bunny_connection():
    """Test la connexion Bunny CDN avec les credentials fournis"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        data = request.get_json()
        api_key = data.get('api_key')
        library_id = data.get('library_id')
        
        if not api_key or not library_id:
            return jsonify({"error": "API Key et Library ID requis"}), 400
        
        # Tester la connexion
        import requests
        
        test_url = f"https://video.bunnycdn.com/library/{library_id}/videos"
        headers = {
            "AccessKey": api_key,
            "Accept": "application/json"
        }
        
        response = requests.get(test_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return jsonify({
                "success": True,
                "message": "Connexion Bunny CDN réussie",
                "library_id": library_id
            }), 200
        elif response.status_code == 401:
            return jsonify({
                "success": False,
                "message": "Authentification échouée - Vérifiez votre API Key"
            }), 401
        else:
            return jsonify({
                "success": False,
                "message": f"Erreur de connexion: {response.status_code}"
            }), 400
            
    except requests.exceptions.Timeout:
        return jsonify({
            "success": False,
            "message": "Timeout - Impossible de contacter Bunny CDN"
        }), 408
    except Exception as e:
        logger.error(f"Erreur test Bunny: {e}")
        return jsonify({
            "success": False,
            "message": f"Erreur: {str(e)}"
        }), 500


# --- ROUTES DE VISUALISATION DES LOGS ---

@admin_bp.route("/logs", methods=["GET"])
def get_system_logs():
    """Récupère les logs système (dernières lignes du fichier log)"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Paramètres
        lines = request.args.get('lines', 100, type=int)
        lines = min(lines, 1000)  # Maximum 1000 lignes
        
        log_level = request.args.get('level', 'all')  # all, error, warning, info
        
        # Chercher le fichier de log
        log_file_path = None
        possible_paths = [
            'app.log',
            'logs/app.log',
            '../app.log',
            'padelvar.log'
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                log_file_path = path
                break
        
        if not log_file_path:
            return jsonify({
                "logs": [],
                "message": "Fichier de log introuvable",
                "total_lines": 0
            }), 200
        
        # Lire les dernières lignes
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
        
        # Prendre les N dernières lignes
        recent_lines = all_lines[-lines:]
        
        # Filtrer par niveau si nécessaire
        if log_level != 'all':
            level_upper = log_level.upper()
            recent_lines = [line for line in recent_lines if level_upper in line]
        
        # Parser les lignes pour extraire les informations
        parsed_logs = []
        for line in recent_lines:
            parsed_log = {
                'raw': line.strip(),
                'timestamp': None,
                'level': 'INFO',
                'message': line.strip()
            }
            
            # Tentative d'extraction du niveau
            if 'ERROR' in line:
                parsed_log['level'] = 'ERROR'
            elif 'WARNING' in line:
                parsed_log['level'] = 'WARNING'
            elif 'INFO' in line:
                parsed_log['level'] = 'INFO'
            elif 'DEBUG' in line:
                parsed_log['level'] = 'DEBUG'
            
            parsed_logs.append(parsed_log)
        
        return jsonify({
            "logs": parsed_logs,
            "total_lines": len(parsed_logs),
            "log_file": log_file_path,
            "filter": log_level
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lecture logs: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/logs/download", methods=["GET"])
def download_logs():
    """Télécharge le fichier de log complet"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        from flask import send_file
        
        log_file_path = None
        possible_paths = ['app.log', 'logs/app.log', '../app.log']
        
        for path in possible_paths:
            if os.path.exists(path):
                log_file_path = path
                break
        
        if not log_file_path:
            return jsonify({"error": "Fichier de log introuvable"}), 404
        
        return send_file(
            log_file_path,
            as_attachment=True,
            download_name=f'padelvar_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
            mimetype='text/plain'
        )
        
    except Exception as e:
        logger.error(f"Erreur téléchargement logs: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/logs/clear", methods=["POST"])
def clear_logs():
    """Vide le fichier de log (crée une sauvegarde avant)"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        log_file_path = None
        possible_paths = ['app.log', 'logs/app.log', '../app.log']
        
        for path in possible_paths:
            if os.path.exists(path):
                log_file_path = path
                break
        
        if not log_file_path:
            return jsonify({"error": "Fichier de log introuvable"}), 404
        
        # Créer une sauvegarde
        backup_path = f"{log_file_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        import shutil
        shutil.copy2(log_file_path, backup_path)
        
        # Vider le fichier
        with open(log_file_path, 'w') as f:
            f.write(f"# Logs cleared by admin at {datetime.now().isoformat()}\n")
        
        logger.info(f"Logs vidés par admin - Sauvegarde: {backup_path}")
        
        return jsonify({
            "message": "Logs vidés avec succès",
            "backup": backup_path
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur vidage logs: {e}")
        return jsonify({"error": str(e)}), 500
