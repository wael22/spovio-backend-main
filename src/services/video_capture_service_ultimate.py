"""
Service de capture vidéo PadelVar - VERSION FINALE ROBUSTE
FFmpeg + fallback OpenCV + durée exacte garantie
"""

import os
import time
import logging
import subprocess
import threading
import shutil
import json
from pathlib import Path
import psutil
import cv2

logger = logging.getLogger(__name__)


class DirectVideoCaptureService:
    def __init__(self):
        self.active_recordings = {}
        ffmpeg_dir = r"C:\ffmpeg\ffmpeg-7.1.1-essentials_build\bin"
        self.ffmpeg_path = os.path.join(ffmpeg_dir, "ffmpeg.exe")
        self.ffprobe_path = os.path.join(ffmpeg_dir, "ffprobe.exe")

    # ------------------ UTILITAIRES ------------------

    def _test_camera_connectivity(self, camera_url, timeout=10):
        """Tester la connectivité de la caméra avant enregistrement"""
        logger.info(f"🔍 Test connectivité caméra: {camera_url}")
        
        try:
            import requests
            
            # Test HTTP simple pour MJPG
            if 'mjpg' in camera_url.lower() or 'axis-cgi' in camera_url.lower():
                logger.info("📡 Test HTTP pour caméra MJPG...")
                response = requests.head(camera_url, timeout=timeout)
                
                if response.status_code == 200:
                    logger.info(f"✅ Caméra accessible (HTTP {response.status_code})")
                    return True
                else:
                    logger.warning(f"⚠️ Caméra répond HTTP {response.status_code}")
                    return False
            else:
                # Pour autres types de flux, test OpenCV rapide
                logger.info("📹 Test OpenCV rapide...")
                import cv2
                cap = cv2.VideoCapture(camera_url)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                
                # Tenter de lire une frame
                ret, frame = cap.read()
                cap.release()
                
                if ret and frame is not None:
                    logger.info("✅ Caméra accessible (frame test OK)")
                    return True
                else:
                    logger.warning("⚠️ Impossible de lire frame caméra")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Erreur test connectivité: {e}")
            return False

    def force_cleanup(self):
        """Nettoyage forcé des processus FFmpeg orphelins"""
        try:
            cleaned_count = 0
            for process in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if 'ffmpeg' in process.info['name'].lower():
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except psutil.TimeoutExpired:
                            process.kill()
                        cleaned_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            if cleaned_count > 0:
                logger.info(f"{cleaned_count} processus FFmpeg nettoyés")
        except Exception as e:
            logger.error(f"Erreur nettoyage forcé: {e}")

    def _get_video_duration_accurate(self, video_path):
        """Durée exacte via ffprobe"""
        logger.info(f"🔍 FFprobe analyse durée: {video_path}")
        
        try:
            cmd = [
                self.ffprobe_path,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                video_path
            ]
            
            logger.info(f"🔧 Commande ffprobe: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            logger.info(f"📊 FFprobe return code: {result.returncode}")
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                logger.info(f"📋 FFprobe data keys: {list(data.keys())}")
                
                if "format" in data and "duration" in data["format"]:
                    raw_duration = float(data["format"]["duration"])
                    rounded_duration = int(round(raw_duration))
                    
                    logger.info(f"⏱️ FFprobe durée brute: {raw_duration:.3f}s")
                    logger.info(f"⏱️ FFprobe durée arrondie: {rounded_duration}s")
                    
                    # Informations supplémentaires utiles
                    if "format" in data:
                        format_info = data["format"]
                        size = format_info.get("size", "unknown")
                        bitrate = format_info.get("bit_rate", "unknown")
                        logger.info(f"📁 Taille fichier: {size} bytes")
                        logger.info(f"📊 Bitrate: {bitrate}")
                    
                    return rounded_duration
                else:
                    logger.warning("⚠️ Pas de durée trouvée dans format")
                    logger.info(f"📋 Format data: {data.get('format', {})}")
            else:
                logger.error(f"❌ FFprobe erreur: {result.stderr}")
                
        except Exception as e:
            logger.error(f"❌ Exception ffprobe: {e}")
        
        logger.warning("⚠️ FFprobe retourne None")
        return None

    def _repair_video_metadata(self, input_path):
        """Réparer MP4 corrompu avec stratégies multiples"""
        if not Path(input_path).exists():
            logger.error(f"❌ Fichier inexistant: {input_path}")
            return False
            
        file_size = Path(input_path).stat().st_size
        logger.info(f"🔍 Réparation fichier: {file_size:,} bytes")
        
        if file_size < 1024:
            logger.warning(f"⚠️ Fichier trop petit: {file_size} bytes")
            return False

        temp_path = str(input_path).replace('.mp4', '_repaired.mp4')
        
        try:
            # Stratégie 1: Réparation simple avec copy + faststart + genpts
            logger.info("🔧 Stratégie 1: Réparation métadonnées avec timeline...")
            cmd1 = [
                self.ffmpeg_path, "-y", 
                "-fflags", "+genpts",  # ✅ Force recalcul timeline
                "-i", input_path,
                "-c", "copy",
                "-movflags", "+faststart+frag_keyframe+empty_moov",
                "-f", "mp4", temp_path
            ]
            
            result = subprocess.run(cmd1, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and Path(temp_path).exists():
                temp_size = Path(temp_path).stat().st_size
                if temp_size > file_size * 0.8:  # Au moins 80% de la taille originale
                    shutil.move(temp_path, input_path)
                    logger.info(f"✅ Stratégie 1 réussie: {temp_size:,} bytes")
                    return True
                else:
                    logger.warning(f"⚠️ Fichier réparé trop petit: {temp_size:,} bytes")
                    Path(temp_path).unlink()
                    
            # Stratégie 2: Re-encoding léger si la première échoue
            logger.info("🔧 Stratégie 2: Re-encoding MP4...")
            temp_path2 = str(input_path).replace('.mp4', '_reencoded.mp4')
            
            cmd2 = [
                self.ffmpeg_path, "-y", "-i", input_path,
                "-c:v", "libx264", "-preset", "ultrafast",
                "-crf", "23", "-c:a", "copy",
                "-movflags", "+faststart",
                "-f", "mp4", temp_path2
            ]
            
            result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=60)
            
            if result2.returncode == 0 and Path(temp_path2).exists():
                temp_size2 = Path(temp_path2).stat().st_size
                if temp_size2 > 1000:  # Au moins 1KB
                    shutil.move(temp_path2, input_path)
                    logger.info(f"✅ Stratégie 2 réussie: {temp_size2:,} bytes")
                    return True
                else:
                    Path(temp_path2).unlink()
                    
        except subprocess.TimeoutExpired:
            logger.error("❌ Timeout lors de la réparation")
        except Exception as e:
            logger.error(f"❌ Erreur réparation: {e}")
        finally:
            # Nettoyage des fichiers temporaires
            for temp_file in [temp_path, str(input_path).replace('.mp4', '_reencoded.mp4')]:
                if Path(temp_file).exists():
                    try:
                        Path(temp_file).unlink()
                    except:
                        pass
                        
        logger.error("❌ Toutes les stratégies de réparation ont échoué")
        return False

    # ------------------ OPEN CV FALLBACK ------------------

    def _record_with_opencv(self, camera_url, output_path, duration=10, fps=10):
        """Enregistrement fallback OpenCV avec gestion durée longue"""
        cap = cv2.VideoCapture(camera_url)
        if not cap.isOpened():
            logger.error("Impossible d'ouvrir la caméra avec OpenCV")
            return False

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

        logger.info(f"🎥 OpenCV: Démarrage {duration}s à {fps} FPS ({width}x{height})")
        
        start = time.time()
        frame_count = 0
        last_log = 0
        
        while time.time() - start < duration:
            ret, frame = cap.read()
            if not ret:
                logger.warning("⚠️ OpenCV: Frame perdu")
                time.sleep(0.1)  # Petite pause en cas d'erreur
                continue
                
            out.write(frame)
            frame_count += 1
            
            # Log progression toutes les 30 secondes pour durées longues
            elapsed = time.time() - start
            if elapsed - last_log > 30:
                logger.info(f"🎬 OpenCV: {elapsed:.0f}s/{duration}s - {frame_count} frames")
                last_log = elapsed
            
            time.sleep(1.0 / fps)

        cap.release()
        out.release()
        
        final_elapsed = time.time() - start
        logger.info(f"✅ OpenCV terminé: {final_elapsed:.1f}s - {frame_count} frames")
        return Path(output_path).exists() and Path(output_path).stat().st_size > 1000

    def _record_with_opencv_async(self, camera_url, output_path, duration, stop_event):
        """OpenCV asynchrone avec stop_event pour arrêt manuel"""
        cap = cv2.VideoCapture(camera_url)
        if not cap.isOpened():
            logger.error("Impossible d'ouvrir la caméra avec OpenCV async")
            return False

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(str(output_path), fourcc, 10, (width, height))

        logger.info(f"🎥 OpenCV async: {duration}s à 10 FPS ({width}x{height})")
        
        start = time.time()
        frame_count = 0
        last_log = 0
        
        while (time.time() - start < duration) and not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                logger.warning("⚠️ OpenCV async: Frame perdu")
                time.sleep(0.1)
                continue
                
            out.write(frame)
            frame_count += 1
            
            # Log progression toutes les 30 secondes
            elapsed = time.time() - start
            if elapsed - last_log > 30:
                logger.info(f"🎬 OpenCV async: {elapsed:.0f}s/{duration}s - {frame_count} frames")
                last_log = elapsed
            
            time.sleep(0.1)  # 10 FPS

        cap.release()
        out.release()
        
        final_elapsed = time.time() - start
        reason = "arrêt manuel" if stop_event.is_set() else "durée atteinte"
        logger.info(f"✅ OpenCV async terminé: {final_elapsed:.1f}s ({reason}) - {frame_count} frames")
        return Path(output_path).exists() and Path(output_path).stat().st_size > 1000
    # ------------------ ENREGISTREMENT ------------------

    def start_recording(self, session_id, camera_url, output_path,
                        max_duration=None, user_id=None, court_id=None,
                        session_name="Enregistrement"):
        """Lancer enregistrement via FFmpeg"""
        if session_id in self.active_recordings:
            self.stop_recording(session_id)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # 🔍 TEST CONNECTIVITÉ CAMÉRA AVANT ENREGISTREMENT
        logger.info(f"🚀 Démarrage enregistrement {session_id}")
        if not self._test_camera_connectivity(camera_url, timeout=5):
            logger.error(f"❌ Caméra inaccessible: {camera_url}")
            logger.error("🔍 Vérifiez:")
            logger.error("   • Connexion réseau")
            logger.error("   • URL caméra correcte")
            logger.error("   • Caméra allumée/fonctionnelle")
            return {'success': False, 'error': 'Caméra inaccessible'}
        
        logger.info("✅ Caméra accessible - démarrage FFmpeg...")

        cmd = [
            self.ffmpeg_path, "-y",
            "-use_wallclock_as_timestamps", "1",
            "-fflags", "+genpts",  # Force recalcul timestamps
            "-i", camera_url,
            "-t", str(max_duration),  # DURÉE EXACTE
            "-c:v", "libx264", "-preset", "ultrafast",
            "-profile:v", "baseline", "-level", "3.0",
            "-pix_fmt", "yuv420p", "-crf", "28",
            "-r", "15", "-g", "30",
            "-an",
            "-movflags", "+faststart+frag_keyframe+empty_moov",
            "-f", "mp4",
            output_path
        ]

        # Ajustements spéciaux pour flux MJPG et Axis
        if "mjpg" in camera_url.lower() or "mjpeg" in camera_url.lower() or "axis-cgi" in camera_url.lower():
            logger.info("🎥 Détection flux MJPG - paramètres optimisés")
            cmd = [
                self.ffmpeg_path, "-y",
                "-analyzeduration", "3000000",    # 3s analyse
                "-probesize", "3000000",          # 3MB sonde
                "-user_agent", "PadelVar/1.0",
                "-fflags", "+genpts",             # Force recalcul timestamps
                "-i", camera_url,
                "-t", str(max_duration),          # DURÉE EXACTE
                "-c:v", "libx264", "-preset", "ultrafast",
                "-profile:v", "baseline", "-level", "3.0",
                "-pix_fmt", "yuv420p", "-crf", "30",
                "-r", "8", "-g", "16",
                "-an",
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart+frag_keyframe+empty_moov",
                "-f", "mp4",
                output_path
            ]
            
            # DEBUG: Afficher commande exacte
            cmd_debug = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd)
            logger.info(f"🔍 Commande FFmpeg: {cmd_debug}")
            
            process = subprocess.Popen(
                cmd, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True
            )

        # Enregistrer processus FFmpeg immédiatement
        self.active_recordings[session_id] = {
            'process': process,
            'output_path': output_path,
            'start_time': time.time(),
            'camera_url': camera_url,
            'max_duration': max_duration  # Sauvegarder durée prévue
        }
        logger.info(f"✅ FFmpeg démarré PID {process.pid} pour {session_id} ({max_duration}s)")
        return {'success': True, 'session_id': session_id, 'file': output_path}

    def stop_recording(self, session_id):
        """Arrêter FFmpeg proprement, valider ou fallback OpenCV"""
        if session_id not in self.active_recordings:
            return {'success': False, 'error': 'Session introuvable'}

        info = self.active_recordings[session_id]
        process = info['process']
        output_path = info['output_path']
        theoretical_duration = int(time.time() - info['start_time'])

        try:
            # Gérer arrêt OpenCV asynchrone
            if info.get('opencv_mode') and info.get('stop_event'):
                logger.info(f"🛑 Arrêt OpenCV session {session_id}...")
                info['stop_event'].set()  # Signal d'arrêt au thread
                
                # Attendre que le thread se termine
                opencv_thread = info.get('opencv_thread')
                if opencv_thread:
                    opencv_thread.join(timeout=5)
                    if opencv_thread.is_alive():
                        logger.warning("⚠️ Thread OpenCV ne répond pas")
                    else:
                        logger.info("✅ Thread OpenCV terminé")
            
            # Gérer arrêt FFmpeg normal
            elif process and process.poll() is None:
                logger.info(f"🛑 Arrêt FFmpeg session {session_id} avec SIGINT propre...")
                
                # SIGINT (CTRL+C) pour arrêt propre - permet finalisation MP4
                import signal
                try:
                    if hasattr(signal, 'CTRL_C_EVENT'):  # Windows
                        process.send_signal(signal.CTRL_C_EVENT)
                    else:  # Unix/Linux
                        process.send_signal(signal.SIGINT)
                    
                    process.wait(timeout=10)  # Plus de temps pour finalisation
                    logger.info("✅ SIGINT propre réussi - MP4 finalisé")
                except subprocess.TimeoutExpired:
                    logger.warning("⚠️ SIGINT timeout - SIGTERM forcé")
                    process.terminate()
                    process.wait(timeout=5)
                    logger.info("✅ SIGTERM appliqué")
                except Exception as e:
                    logger.warning(f"⚠️ SIGINT échoué: {e} - SIGTERM forcé")
                    process.terminate()
                    process.wait(timeout=5)

            # Attendre stabilisation fichier (CRITIQUE pour MP4)
            time.sleep(2)
            logger.info(f"🔍 Vérification fichier: {output_path}")

            # Si le fichier n'existe pas ou est trop petit, fallback OpenCV
            # MAIS seulement si pas déjà en mode OpenCV !
            if (not info.get('opencv_mode') and 
                (not os.path.exists(output_path) or os.path.getsize(output_path) < 1024)):
                logger.warning("⚠️ Fichier FFmpeg invalide - fallback OpenCV")
                # Utiliser la durée maximale prévue, pas limitée à 30s
                planned_duration = info.get('max_duration', theoretical_duration * 60) / 60  # En minutes
                opencv_duration = min(planned_duration * 60, 7200)  # Max 2h pour éviter abus
                logger.info(f"🎥 Fallback OpenCV: {opencv_duration}s prévus")
                
                success = self._record_with_opencv(info['camera_url'], output_path, opencv_duration)
                if not success:
                    logger.error("❌ Fallback OpenCV échoué")
                    return {'success': False, 'error': 'Enregistrement échoué'}
            
            # FINALISATION MP4 AUTOMATIQUE pour résoudre 0xc00d36c4
            file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            logger.info(f"📊 Fichier brut créé: {file_size:,} bytes")
            
            # 🚨 DIAGNOSTIC FICHIER TROP PETIT
            if file_size < 1024:  # Moins de 1KB = échec critique
                logger.error(f"🚨 FICHIER TROP PETIT: {file_size} bytes!")
                logger.error("❌ FFmpeg a probablement échoué à capturer la vidéo")
                logger.error(f"🔍 Causes possibles:")
                logger.error(f"   • Caméra inaccessible: {info['camera_url']}")
                logger.error(f"   • Flux MJPG corrompu ou interrompu")
                logger.error(f"   • Problème réseau ou timeout")
                logger.error(f"   • Permissions insuffisantes")
                
                # Tentative fallback OpenCV si échec FFmpeg total
                logger.info("🔄 Tentative fallback OpenCV d'urgence...")
                opencv_duration = min(theoretical_duration, 30)  # Max 30s pour éviter blocage
                success = self._record_with_opencv(info['camera_url'], output_path, opencv_duration)
                
                if success:
                    file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
                    logger.info(f"✅ Fallback OpenCV réussi: {file_size:,} bytes")
                    duration = opencv_duration
                else:
                    logger.error("❌ Fallback OpenCV échoué aussi")
                    return {'success': False, 'error': 'Capture vidéo impossible - caméra inaccessible'}
            
            elif file_size > 1024:
                # Finaliser fichier avant upload
                logger.info("🔧 FINALISATION MP4 automatique...")
                if self._finalize_mp4(output_path):
                    logger.info("✅ MP4 finalisé - fichier lisible partout")
                    duration = self._get_video_duration_accurate(output_path) or theoretical_duration
                    
                    # 📊 LOGS COMPARAISON DURÉES
                    logger.info(f"🕐 COMPARAISON DURÉES après finalisation:")
                    logger.info(f"   ⏱️ Durée théorique (timer): {theoretical_duration}s")
                    logger.info(f"   🎥 Durée réelle (ffprobe): {duration}s")
                    if duration != theoretical_duration:
                        diff = abs(duration - theoretical_duration)
                        logger.warning(f"   ⚠️ Écart détecté: {diff}s")
                    else:
                        logger.info("   ✅ Durées correspondent parfaitement")
                else:
                    logger.warning("⚠️ Finalisation échouée - tentative réparation...")
                    if self._repair_video_metadata(output_path):
                        logger.info("✅ Réparation de secours réussie")
                        duration = self._get_video_duration_accurate(output_path) or theoretical_duration
                        
                        # 📊 LOGS APRÈS RÉPARATION
                        logger.info(f"🔧 DURÉES après réparation:")
                        logger.info(f"   ⏱️ Durée théorique: {theoretical_duration}s")
                        logger.info(f"   🎥 Durée réparée: {duration}s")
                    else:
                        logger.error("❌ Impossible de corriger le fichier MP4")
                        duration = theoretical_duration
            else:
                logger.warning("⚠️ Fichier trop petit - fallback OpenCV")
                success = self._record_with_opencv(info['camera_url'], output_path, min(theoretical_duration, 30))
                if not success:
                    logger.error("❌ Fallback OpenCV échoué")
                    return {'success': False, 'error': 'Enregistrement échoué'}
                duration = theoretical_duration

            # Nettoyage session
            del self.active_recordings[session_id]
            
            # Nettoyage automatique des processus orphelins pour éviter fuites mémoire
            try:
                self.force_cleanup()
            except Exception as e:
                logger.warning(f"⚠️ Nettoyage processus échoué: {e}")
            
            # Calcul taille finale après post-traitement
            final_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            
            return {
                'success': True,
                'session_id': session_id,
                'output_file': output_path,
                'duration': duration,
                'file_size': final_size
            }

        except Exception as e:
            logger.error(f"Erreur arrêt: {e}")
            if session_id in self.active_recordings:
                del self.active_recordings[session_id]
            return {'success': False, 'error': str(e)}

    def _finalize_mp4(self, input_path):
        """Convertit un MP4 fragmenté en MP4 standard lisible partout - optimisé MJPG"""
        if not os.path.exists(input_path):
            logger.error(f"Fichier non trouvé: {input_path}")
            return False
            
        fixed_path = input_path.replace(".mp4", "_final.mp4")
        
        try:
            logger.info("🔧 Finalisation MP4 pour compatibilité universelle...")
            
            # Analyse rapide du fichier source
            probe_cmd = [
                'ffprobe', "-v", "quiet", "-print_format", "json",
                "-show_streams", input_path
            ]
            
            use_copy = True
            try:
                result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    logger.warning("⚠️ Fichier source problématique - ré-encodage nécessaire")
                    use_copy = False
            except:
                logger.warning("⚠️ Analyse impossible - ré-encodage par sécurité")
                use_copy = False
            
            if use_copy:
                # Tentative de copie simple avec correction des métadonnées
                cmd = [
                    self.ffmpeg_path, "-y",
                    "-i", input_path,
                    "-c", "copy",
                    "-avoid_negative_ts", "make_zero",
                    "-fflags", "+genpts",
                    "-movflags", "+faststart",
                    fixed_path
                ]
            else:
                # Ré-encodage minimal pour flux MJPG corrompus
                cmd = [
                    self.ffmpeg_path, "-y",
                    "-i", input_path,
                    "-c:v", "libx264", "-preset", "veryfast",
                    "-profile:v", "main", "-level", "3.1",
                    "-pix_fmt", "yuv420p",
                    "-an",
                    "-movflags", "+faststart",
                    fixed_path
                ]
            
            logger.info(f"🎬 Finalisation: {' '.join(cmd[:8])}...")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=45, check=False)
            
            if result.returncode == 0 and Path(fixed_path).exists():
                # Vérifier que le fichier finalisé est valide
                final_size = Path(fixed_path).stat().st_size
                original_size = Path(input_path).stat().st_size
                
                if final_size > 1000:  # Au moins quelques KB
                    # Validation finale avec ffprobe
                    validate_cmd = ['ffprobe', "-v", "quiet", fixed_path]
                    validate_result = subprocess.run(validate_cmd, capture_output=True, timeout=5)
                    
                    if validate_result.returncode == 0:
                        os.replace(fixed_path, input_path)  # Remplace l'original
                        logger.info(f"✅ MP4 finalisé et validé: {input_path} ({final_size:,} bytes)")
                        return True
                    else:
                        logger.error("❌ Fichier finalisé invalide")
                        if os.path.exists(fixed_path):
                            os.remove(fixed_path)
                        return False
                else:
                    logger.warning(f"⚠️ Fichier finalisé trop petit: {final_size:,} bytes")
                    if os.path.exists(fixed_path):
                        os.remove(fixed_path)
                    return False
            else:
                logger.error(f"❌ Post-traitement échoué: {result.stderr[:300]}")
                return False
                
        except Exception as e:
            logger.error(f"Erreur finalisation MP4: {e}")
            if os.path.exists(fixed_path):
                try:
                    os.remove(fixed_path)
                except:
                    pass
            return False

    # ------------------ COMPATIBILITÉ AVEC L'API EXISTANTE ------------------

    def is_recording(self, session_id=None):
        """Vérifier si une session spécifique ou globalement en cours"""
        if session_id:
            return session_id in self.active_recordings
        return len(self.active_recordings) > 0

    def get_recording_duration(self, session_id=None):
        """Durée d'enregistrement pour une session"""
        if session_id and session_id in self.active_recordings:
            return int(time.time() - self.active_recordings[session_id]['start_time'])
        return 0

    def get_status(self, session_id=None):
        """Statut d'une session ou général"""
        if session_id and session_id in self.active_recordings:
            info = self.active_recordings[session_id]
            return {
                "recording": True,
                "pid": info['process'].pid,
                "duration": self.get_recording_duration(session_id),
                "start_time": info['start_time'],
                "session_id": session_id,
                "output_path": info['output_path']
            }
        return {
            "recording": False,
            "active_sessions": list(self.active_recordings.keys()),
            "session_count": len(self.active_recordings)
        }
