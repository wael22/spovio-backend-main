"""
Routes Live Streaming HLS — Spovio Padel
Architecture:
  Caméra MJPEG → FFmpeg → segments .ts + playlist .m3u8 (HLS)
                     └─► Flask sert les segments → HLS.js (viewers)

Un seul encodage FFmpeg partagé par tous les spectateurs.
Supporte ~100-500 viewers sur le VPS OVH.
"""
import os
import shutil
import random
import string
import threading
import subprocess
import time
from datetime import datetime
from flask import (Blueprint, request, jsonify, send_from_directory,
                   Response, current_app)

live_bp = Blueprint('live', __name__)
_lock = threading.Lock()

# ─── État global des lives ────────────────────────────────────────────
# { code: { stream_url, team_a, team_b, logo_url, club_name,
#           hls_dir, ffmpeg_proc, started_at, active, started_by,
#           viewer_count } }
_lives: dict = {}

HLS_BASE = os.path.join(os.path.sep, 'tmp', 'hls')   # Linux VPS
if os.name == 'nt':                                    # Windows dev
    HLS_BASE = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'spovio_hls')


def _gen_code(length=6):
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        if code not in _lives:
            return code


def _get_session_user():
    from flask import session as flask_session
    from src.models.user import User
    uid = flask_session.get('user_id')
    if not uid:
        return None
    return User.query.get(uid)


def _find_ffmpeg():
    """Trouve FFmpeg : variable d'environnement, PATH, ou chemins connus."""
    env_path = os.environ.get('FFMPEG_PATH')
    if env_path and os.path.isfile(env_path):
        return env_path
    # Chercher dans PATH
    for cmd in ('ffmpeg', 'ffmpeg.exe'):
        found = shutil.which(cmd)
        if found:
            return found
    # Chemins Windows connus
    for p in [
        r'C:\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe',
        r'C:\ffmpeg\bin\ffmpeg.exe',
    ]:
        if os.path.isfile(p):
            return p
    return None


def _start_ffmpeg_hls(stream_url: str, hls_dir: str) -> subprocess.Popen | None:
    """
    Lance FFmpeg pour convertir le flux caméra en segments HLS.
    Retourne le process ou None en cas d'erreur.
    """
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return None

    os.makedirs(hls_dir, exist_ok=True)
    playlist = os.path.join(hls_dir, 'stream.m3u8')

    cmd = [
        ffmpeg, '-hide_banner',
        # Input
        '-i', stream_url,
        # Encodage léger (CPU ~5-10%)
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-tune', 'zerolatency',
        '-crf', '28',           # qualité raisonnable (23=haute, 28=stream)
        '-r', '25',             # 25 fps
        '-g', '50',             # GOP = 2s (keyframe interval)
        '-sc_threshold', '0',
        # Pas d'audio pour MJPEG par sécurité (évite crash FFmpeg)
        '-an',
        # HLS output
        '-f', 'hls',
        '-hls_time', '4',           # segments de 4s
        '-hls_list_size', '6',      # 6 segments en playlist (~24s de buffer)
        '-hls_flags', 'delete_segments+append_list+discont_start',
        '-hls_segment_filename', os.path.join(hls_dir, 'seg%05d.ts'),
        playlist,
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True
        )
        # Attendre que la playlist soit créée (max 30s)
        for _ in range(60):
            if proc.poll() is not None:
                err = proc.stderr.read()
                current_app.logger.error(f"❌ FFmpeg HLS crashed prematurely. Code: {proc.returncode}. Erreur: {err}")
                return None
            if os.path.exists(playlist):
                return proc
            time.sleep(0.5)
        # Timeout : tuer le process
        proc.terminate()
        try:
            err = proc.stderr.read()
            current_app.logger.error(f"❌ FFmpeg HLS Timeout. Stderr: {err}")
        except:
            pass
        return None
    except Exception as e:
        current_app.logger.error(f"❌ FFmpeg HLS erreur: {e}")
        return None


# ─── Pages HTML ───────────────────────────────────────────────────────
@live_bp.route('/live')
def live_launcher_page():
    static_dir = os.path.join(os.path.dirname(__file__), '..', 'static')
    return send_from_directory(static_dir, 'live_launcher.html')


@live_bp.route('/watch/<code>')
def watch_page(code):
    static_dir = os.path.join(os.path.dirname(__file__), '..', 'static')
    return send_from_directory(static_dir, 'watch.html')


# ─── Servir segments HLS (public, sans auth) ─────────────────────────
@live_bp.route('/api/live/<code>/hls/<path:filename>')
def serve_hls(code, filename):
    """
    Sert les fichiers HLS : stream.m3u8 et seg*.ts
    Utilisé par HLS.js dans le navigateur.
    """
    with _lock:
        live = _lives.get(code)

    if not live or not live.get('active'):
        return Response('Live terminé', status=404)

    hls_dir = live.get('hls_dir', '')
    if not hls_dir or not os.path.isdir(hls_dir):
        return Response('HLS non prêt', status=503)

    filepath = os.path.join(hls_dir, filename)
    if not os.path.exists(filepath):
        return Response('Segment introuvable', status=404)

    mime = 'application/vnd.apple.mpegurl' if filename.endswith('.m3u8') else 'video/mp2t'
    return send_from_directory(hls_dir, filename, mimetype=mime,
                               max_age=0)


# ─── Info live (public) ───────────────────────────────────────────────
@live_bp.route('/api/live/<code>/info')
def live_info(code):
    with _lock:
        live = _lives.get(code)
    if not live:
        return jsonify({'error': 'Live introuvable'}), 404

    # Score depuis arbitre_routes
    score = {}
    try:
        from src.routes.arbitre_routes import _state_snapshot
        score = _state_snapshot()
    except Exception:
        pass

    return jsonify({
        'code':         code,
        'active':       live.get('active', False),
        'team_a':       live.get('team_a', score.get('team_a', 'Équipe A')),
        'team_b':       live.get('team_b', score.get('team_b', 'Équipe B')),
        'logo_url':     live.get('logo_url', ''),
        'club_name':    live.get('club_name', ''),
        'viewer_count': live.get('viewer_count', 0),
        'score':        score,
    }), 200


# ─── Heartbeat viewer ─────────────────────────────────────────────────
@live_bp.route('/api/live/<code>/heartbeat', methods=['POST'])
def viewer_heartbeat(code):
    """Chaque spectateur ping toutes les 10s. Incrémente le compteur."""
    viewer_id = request.get_json(silent=True, force=True).get('viewer_id', '') if request.data else ''
    with _lock:
        live = _lives.get(code)
        if live and live.get('active'):
            ts = live.setdefault('_viewers', {})
            ts[viewer_id or request.remote_addr] = time.time()
            # Nettoyer les viewers inactifs (> 20s)
            cutoff = time.time() - 20
            live['_viewers'] = {k: v for k, v in ts.items() if v > cutoff}
            live['viewer_count'] = len(live['_viewers'])
    return jsonify({'ok': True}), 200


# ─── Démarrer un live ─────────────────────────────────────────────────
@live_bp.route('/api/live/start', methods=['POST'])
def start_live():
    """
    Corps JSON:
      camera_url  (str)  — URL MJPEG/RTSP de la caméra
      team_a, team_b (str)
      logo_url    (str, optionnel)
    """
    try:
        user = _get_session_user()
        if not user:
            return jsonify({'error': 'Non authentifié'}), 401

        data       = request.get_json(silent=True) or {}
        camera_url = data.get('camera_url', '').strip()
        team_a     = data.get('team_a', 'Équipe A')
        team_b     = data.get('team_b', 'Équipe B')
        logo_url   = data.get('logo_url', '')

        if not camera_url:
            return jsonify({'error': 'camera_url requis'}), 400

        if not _find_ffmpeg():
            return jsonify({'error': 'FFmpeg non trouvé sur ce serveur. Installez FFmpeg.'}), 503

        code    = _gen_code()
        hls_dir = os.path.join(HLS_BASE, code)

        # Démarrer FFmpeg dans un thread pour ne pas bloquer Flask
        proc_container = [None]
        ready_event = threading.Event()

        def launch():
            proc = _start_ffmpeg_hls(camera_url, hls_dir)
            proc_container[0] = proc
            ready_event.set()

        threading.Thread(target=launch, daemon=True).start()

        # Attendre max 30s que HLS soit prêt
        ready_event.wait(timeout=30)
        proc = proc_container[0]

        if not proc:
            shutil.rmtree(hls_dir, ignore_errors=True)
            return jsonify({'error': 'Impossible de démarrer le stream HLS. Vérifiez l\'URL caméra et FFmpeg.'}), 500

        host = request.host

        with _lock:
            _lives[code] = {
                'code':         code,
                'camera_url':   camera_url,
                'hls_dir':      hls_dir,
                'ffmpeg_proc':  proc,
                'club_name':    getattr(user, 'name', ''),
                'logo_url':     logo_url,
                'team_a':       team_a,
                'team_b':       team_b,
                'started_at':   datetime.utcnow().isoformat(),
                'active':       True,
                'started_by':   user.id,
                'viewer_count': 0,
                '_viewers':     {},
            }

        # Sync noms arbitre
        try:
            from src.routes.arbitre_routes import _match, _write_score_file
            _match['team_a'] = team_a
            _match['team_b'] = team_b
            _write_score_file()
        except Exception:
            pass

        watch_url = f'http://{host}/watch/{code}'
        hls_url   = f'http://{host}/api/live/{code}/hls/stream.m3u8'
        current_app.logger.info(f"🔴 HLS Live démarré: {code} → {watch_url}")

        return jsonify({
            'ok':       True,
            'code':     code,
            'watch_url': watch_url,
            'hls_url':  hls_url,
        }), 201
    except Exception as e:
        import traceback
        current_app.logger.error(f"❌ Erreur FATALE dans start_live: {e}\n{traceback.format_exc()}")
        return jsonify({'error': 'Erreur interne', 'details': str(e)}), 500


# ─── Lister les terrains (club) ───────────────────────────────────────
@live_bp.route('/api/live/courts', methods=['GET'])
def live_courts():
    user = _get_session_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401

    try:
        from src.models.user import Club, Court
        # Récupérer les terrains du club de l'utilisateur
        if not user.club_id:
            return jsonify({'courts': []}), 200
            
        club = Club.query.get(user.club_id)
        if not club:
            return jsonify({'courts': []}), 200

        courts = Court.query.filter_by(club_id=club.id).all()
        courts_data = []

        for c in courts:
            courts_data.append({
                'id': c.id,
                'name': c.name,
                'camera_url': c.camera_url
            })

        return jsonify({'courts': courts_data}), 200

    except Exception as e:
        current_app.logger.error(f"❌ Erreur live_courts: {e}")
        return jsonify({'error': str(e)}), 500


# ─── Arrêter un live ──────────────────────────────────────────────────
@live_bp.route('/api/live/stop', methods=['POST'])
def stop_live():
    user = _get_session_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401

    data = request.get_json(silent=True) or {}
    code = data.get('code')

    if not code:
        with _lock:
            for c, live in _lives.items():
                if live.get('started_by') == user.id and live.get('active'):
                    code = c
                    break

    if not code:
        return jsonify({'error': 'Aucun live actif'}), 404

    with _lock:
        live = _lives.get(code, {})
        live['active'] = False
        live['ended_at'] = datetime.utcnow().isoformat()
        proc    = live.get('ffmpeg_proc')
        hls_dir = live.get('hls_dir', '')

    # Tuer FFmpeg proprement
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    # Nettoyer les segments HLS
    if hls_dir and os.path.isdir(hls_dir):
        shutil.rmtree(hls_dir, ignore_errors=True)

    current_app.logger.info(f"⏹ HLS Live arrêté: {code}")
    return jsonify({'ok': True, 'code': code}), 200


# ─── Live actif de l'utilisateur ─────────────────────────────────────
@live_bp.route('/api/live/my', methods=['GET'])
def my_live():
    user = _get_session_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401

    with _lock:
        for code, live in _lives.items():
            if live.get('started_by') == user.id and live.get('active'):
                safe = {k: v for k, v in live.items()
                        if k not in ('ffmpeg_proc', '_viewers', 'hls_dir')}
                return jsonify({'live': {**safe, 'code': code}}), 200

    return jsonify({'live': None}), 200


# ─── Servir le logo Spovio ────────────────────────────────────────────
@live_bp.route('/static/spovio-logo.png')
def serve_spovio_logo():
    import os
    base = os.path.dirname(__file__)
    candidates = [
        os.path.normpath(os.path.join(base, '..', '..', '..', 'spovio-padel-ai-main', 'src', 'assets', 'spovio-logo-dark.png')),
        os.path.normpath(os.path.join(base, '..', '..', '..', 'spovio-padel-ai-main', 'src', 'assets', 'spovio-logo-new.png')),
        os.path.normpath(os.path.join(base, '..', 'static', 'spovio-logo.png')),
    ]
    for p in candidates:
        if os.path.exists(p):
            return send_from_directory(os.path.dirname(p), os.path.basename(p))
    return Response('Logo non trouvé', status=404)


@live_bp.route('/static/spovio-favicon.png')
def serve_spovio_favicon():
    import os
    base = os.path.dirname(__file__)
    candidates = [
        os.path.normpath(os.path.join(base, '..', '..', '..', 'spovio-padel-ai-main', 'src', 'assets', 'spovio-logo-new.png')),
        os.path.normpath(os.path.join(base, '..', '..', '..', 'spovio-padel-ai-main', 'src', 'assets', 'spovio-logo-dark.png')),
    ]
    for p in candidates:
        if os.path.exists(p):
            return send_from_directory(os.path.dirname(p), os.path.basename(p))
    return Response('Favicon non trouvé', status=404)
