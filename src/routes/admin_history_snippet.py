
@admin_bp.route("/clubs/<int:club_id>/history", methods=["GET"])
def get_club_history_admin(club_id):
    """Récupérer l'historique d'un club (admin uniquement)"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    club = Club.query.get_or_404(club_id)
    
    try:
        # On définit des alias pour les tables User afin de différencier les utilisateurs dans la requête
        Player = aliased(User)
        Performer = aliased(User)
        
        # Récupération de l'historique des actions pour ce club
        history_query = (
            db.session.query(
                ClubActionHistory,
                Player.name.label('player_name'),
                Performer.name.label('performed_by_name')
            )
            .outerjoin(Player, ClubActionHistory.user_id == Player.id)
            .outerjoin(Performer, ClubActionHistory.performed_by_id == Performer.id)
            .filter(ClubActionHistory.club_id == club.id)
            .order_by(ClubActionHistory.performed_at.desc())
            .all()
        )
        
        # Formatage des données pour la réponse
        history_data = []
        for entry, player_name, performed_by_name in history_query:
            history_data.append({
                'id': entry.id,
                'action_type': entry.action_type,
                'action_details': entry.action_details,
                'performed_at': entry.performed_at.isoformat(),
                'player_id': entry.user_id,
                'player_name': player_name,
                'performed_by_id': entry.performed_by_id,
                'performed_by_name': performed_by_name
            })
        
        return jsonify({"history": history_data}), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de l'historique club par admin: {e}")
        return jsonify({"error": "Erreur serveur"}), 500
