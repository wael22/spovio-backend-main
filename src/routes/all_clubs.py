from flask import Blueprint, jsonify
from src.models.user import Club, Court

all_clubs_bp = Blueprint("all_clubs", __name__)

@all_clubs_bp.route("/all", methods=["GET"])
def get_all_clubs():
    try:
        clubs = Club.query.all()
        return jsonify({"clubs": [club.to_dict() for club in clubs]}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@all_clubs_bp.route("/<int:club_id>/courts", methods=["GET"])
def get_club_courts(club_id):
    try:
        # Vérifier que le club existe
        club = Club.query.get(club_id)
        if not club:
            return jsonify({"error": "Club non trouvé"}), 404
        
        # Récupérer les terrains du club
        courts = Court.query.filter_by(club_id=club_id).all()
        
        return jsonify({
            "courts": [court.to_dict() for court in courts]
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
