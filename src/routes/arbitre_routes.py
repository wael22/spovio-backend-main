"""
Routes Arbitre — Tableau de bord Arbitre PADEL
Scoring padel: 0/15/30/40/Avantage + Jeux + Sets
"""
import os, threading
from datetime import datetime
from flask import Blueprint, request, jsonify, send_from_directory, current_app

arbitre_bp = Blueprint('arbitre', __name__)
_lock = threading.Lock()

# Séquence de points padel/tennis
POINTS_SEQ = [0, 15, 30, 40]

def _fresh_state():
    return {
        "team_a": "Équipe A",
        "team_b": "Équipe B",
        # Points dans le jeu en cours (index dans POINTS_SEQ)
        "pt_a": 0,   # 0=0  1=15  2=30  3=40  4=Avantage
        "pt_b": 0,
        # Nombre de jeux dans le set en cours
        "game_a": 0,
        "game_b": 0,
        # Nombre de sets gagnés
        "set_a": 0,
        "set_b": 0,
        "deuce": False,   # True quand 40-40
        "advantage": None,  # 'a' ou 'b' quand avantage
        "timer_running": False,
        "timer_start": None,
        "timer_elapsed": 0,
        "recording_session": None,
        "youtube_active": False,
        "updated_at": datetime.utcnow().isoformat(),
    }

_match = _fresh_state()

SCORE_FILE = os.environ.get("SCORE_FILE", "/tmp/score_overlay.txt")


def _pt_label(idx, deuce, advantage, side):
    """Convertit l'index de point en label lisible."""
    if deuce:
        if advantage == side:
            return "ADV"
        return "40"
    return str(POINTS_SEQ[min(idx, 3)])


def _write_score_file():
    """Écrit le score dans le fichier lu par FFmpeg overlay."""
    s = _match
    pa = _pt_label(s["pt_a"], s["deuce"], s["advantage"], "a")
    pb = _pt_label(s["pt_b"], s["deuce"], s["advantage"], "b")
    line = (f"{s['team_a']}  {s['set_a']} sets  {pa}-{pb}  {s['game_a']}/{s['game_b']}  "
            f"{s['set_b']} sets  {s['team_b']}")
    try:
        with open(SCORE_FILE, "w", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        pass


def _score_point(winner: str):
    """
    Applique la logique de scoring padel au joueur gagnant ('a' ou 'b').
    Met à jour _match sur place.
    """
    loser = "b" if winner == "a" else "a"

    # ── Deuce / Avantage ──
    if _match["deuce"]:
        if _match["advantage"] == winner:
            # Jeu gagné !
            _win_game(winner)
            return
        elif _match["advantage"] == loser:
            # Retour à deuce
            _match["advantage"] = None
            return
        else:
            # premier point après deuce → avantage
            _match["advantage"] = winner
            return

    # ── Progression normale ──
    pw = _match[f"pt_{winner}"]
    pl = _match[f"pt_{loser}"]

    if pw < 3:
        _match[f"pt_{winner}"] += 1
    else:
        # winner était à 40
        if pl == 3:
            # Deuce
            _match["deuce"] = True
            _match["advantage"] = None
        else:
            # Jeu gagné directement
            _win_game(winner)


def _win_game(winner: str):
    """Met à jour les jeux / sets après qu'un joueur remporte un jeu."""
    # Reset points
    _match["pt_a"] = 0
    _match["pt_b"] = 0
    _match["deuce"] = False
    _match["advantage"] = None

    _match[f"game_{winner}"] += 1
    ga = _match["game_a"]
    gb = _match["game_b"]

    # Vérifier si set gagné
    winner_games = ga if winner == "a" else gb
    loser_games  = gb if winner == "a" else ga

    if winner_games >= 6 and winner_games - loser_games >= 2:
        _win_set(winner)
    elif winner_games == 7:   # Tiebreak remporté
        _win_set(winner)


def _win_set(winner: str):
    """Incrémente les sets et remet les jeux à 0."""
    _match["game_a"] = 0
    _match["game_b"] = 0
    _match[f"set_{winner}"] += 1


def _state_snapshot():
    s = dict(_match)
    # Ajouter les labels lisibles
    s["pt_a_label"] = _pt_label(s["pt_a"], s["deuce"], s["advantage"], "a")
    s["pt_b_label"] = _pt_label(s["pt_b"], s["deuce"], s["advantage"], "b")
    return s


# ─── Page HTML ───────────────────────────────────────────────────────────────
@arbitre_bp.route('/arbitre')
def arbitre_page():
    static_dir = os.path.join(os.path.dirname(__file__), '..', 'static')
    return send_from_directory(static_dir, 'arbitre.html')


# ─── API Score ───────────────────────────────────────────────────────────────
@arbitre_bp.route('/api/arbitre/score', methods=['GET'])
def get_score():
    with _lock:
        return jsonify(_state_snapshot()), 200


@arbitre_bp.route('/api/arbitre/score', methods=['POST'])
def update_score():
    """
    action: 'point_a' | 'point_b'   → attribuer un point (logique padel)
            'undo_a'  | 'undo_b'     → annuler le dernier point (reset simple)
            'game_a'  | 'game_b'     → attribuer un jeu directement
            'set_a'   | 'set_b'      → attribuer un set directement
            'reset'                  → tout remettre à zéro
    ou champs libres: team_a, team_b
    """
    data = request.get_json(silent=True) or {}
    action = data.get("action")

    with _lock:
        if action == "point_a":
            _score_point("a")
        elif action == "point_b":
            _score_point("b")
        elif action == "game_a":
            _win_game("a")
        elif action == "game_b":
            _win_game("b")
        elif action == "set_a":
            _win_set("a")
        elif action == "set_b":
            _win_set("b")
        elif action == "reset":
            _match.update(_fresh_state())
            _match["team_a"] = data.get("team_a", _match["team_a"])
            _match["team_b"] = data.get("team_b", _match["team_b"])
        else:
            if "team_a" in data:
                _match["team_a"] = str(data["team_a"])[:20]
            if "team_b" in data:
                _match["team_b"] = str(data["team_b"])[:20]

        _match["updated_at"] = datetime.utcnow().isoformat()
        _write_score_file()
        state = _state_snapshot()

    return jsonify({"ok": True, "state": state}), 200


# ─── API Timer ───────────────────────────────────────────────────────────────
@arbitre_bp.route('/api/arbitre/timer', methods=['POST'])
def timer_control():
    data = request.get_json(silent=True) or {}
    action = data.get("action", "")
    with _lock:
        if action == "start" and not _match["timer_running"]:
            _match["timer_running"] = True
            _match["timer_start"] = datetime.utcnow().isoformat()
        elif action == "pause" and _match["timer_running"]:
            if _match["timer_start"]:
                start_dt = datetime.fromisoformat(_match["timer_start"])
                _match["timer_elapsed"] += (datetime.utcnow() - start_dt).total_seconds()
            _match["timer_running"] = False
            _match["timer_start"] = None
        elif action == "reset":
            _match["timer_running"] = False
            _match["timer_start"] = None
            _match["timer_elapsed"] = 0
        state = _state_snapshot()
    return jsonify({"ok": True, "state": state}), 200


# ─── API Enregistrement ───────────────────────────────────────────────────────
def _internal_headers():
    """Construit les headers pour les appels HTTP internes.
    Transmet le JWT (si présent) ET le cookie de session Flask."""
    hdrs = {}
    # JWT via Authorization header
    token = request.headers.get("Authorization", "")
    if token:
        hdrs["Authorization"] = token
    # Cookie de session Flask (auth basée sur session)
    cookie_header = request.headers.get("Cookie", "")
    if cookie_header:
        hdrs["Cookie"] = cookie_header
    return hdrs


@arbitre_bp.route('/api/arbitre/recording/start', methods=['POST'])
def arbitre_start_recording():
    data = request.get_json(silent=True) or {}
    court_id   = data.get("court_id", 1)
    duration   = data.get("duration_minutes", 60)
    youtube_key= data.get("youtube_key", "")
    try:
        import requests as req
        resp = req.post(
            "http://localhost:5000/api/recording/v3/start",
            json={"court_id": court_id, "duration_minutes": duration},
            headers=_internal_headers(),
            timeout=15,
        )
        if resp.ok:
            body = resp.json()
            with _lock:
                _match["recording_session"] = (
                    body.get("session_id")
                    or (body.get("data") or {}).get("session_id")
                )
                _match["youtube_active"] = bool(youtube_key)
            return jsonify({"ok": True, **body}), 201
        current_app.logger.error(f"❌ Enregistrement 401/erreur: {resp.status_code} {resp.text[:200]}")
        return jsonify({"ok": False, "error": resp.text, "status": resp.status_code}), resp.status_code
    except Exception as e:
        current_app.logger.error(f"❌ Arbitre start: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@arbitre_bp.route('/api/arbitre/recording/stop', methods=['POST'])
def arbitre_stop_recording():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id") or _match.get("recording_session")

    try:
        import requests as req
        hdrs = _internal_headers()

        # Si pas de session_id connu, chercher la session active côté serveur
        if not session_id:
            r_active = req.get(
                "http://localhost:5000/api/recording/v3/my-active",
                headers=hdrs, timeout=10
            )
            if r_active.ok:
                active = r_active.json()
                # La réponse peut être {"session": {...}} ou directement la session
                sess = active.get("session") or active.get("data") or active
                session_id = sess.get("session_id") or sess.get("id")

        resp = req.post(
            "http://localhost:5000/api/recording/v3/stop",
            json={"session_id": session_id},
            headers=hdrs,
            timeout=15,
        )
        with _lock:
            _match["recording_session"] = None
            _match["youtube_active"] = False
        if resp.ok:
            return jsonify({"ok": True, **resp.json()}), 200
        return jsonify({"ok": False, "error": resp.text, "session_tried": session_id}), resp.status_code
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@arbitre_bp.route('/api/arbitre/status', methods=['GET'])
def arbitre_status():
    with _lock:
        state = _state_snapshot()
    return jsonify({
        "match": state,
        "score_file": SCORE_FILE,
        "score_file_exists": os.path.exists(SCORE_FILE),
    }), 200
