"""
ervice de capture vidàÂ©o - nregistrement des flu camàÂ©ra vers stockage local
ptimisàÂ© pour la performance, la fiabilitàÂ© et la gestion des erreurs
"""

import cv
import threading
import time
import os
import logging
import queue
from datetime import datetime, timedelta
from typing import ict, ptional, ny, uple
import uuid
import subprocess
from pathlib import ath
from concurrent.futures import hreadoolecutor
from enum import num

from ..models.database import db
from ..models.user import ideo, ourt, ser
from .bunny_storage_service import bunny_storage_service
from .mjpeg_recording_service import (
    ecordinganager,
    ecordingonfig,
)

# onfiguration du logger
logger  logging.getogger(__name__)

# onfiguration mpeg - tiliser le chemin complet sur indows
_  r"ffmpegffmpeg-..-essentials_buildbinffmpeg.ee"
if not ath(_).eists()
    _  'ffmpeg'
    logger.warning("à¢ÂÂ à¯Â¸Â mpeg non trouvé au chemin complet, utilisation de 'ffmpeg' dans le ")
else
    logger.info(f"✅ mpeg trouvé {_}")

# ouveau chemin ffprobe (corrige inrror )
_  str(ath(_).with_name('ffprobe.ee')) if os.name  'nt' else 'ffprobe'
if os.name  'nt' and not ath(_).eists()
    _  'ffprobe'  # fallback 

class ecordingtatus(num)
    """àÂtats possibles d'un enregistrement"""
      'created'
      'recording'
      'stopping'
      'completed'
      'error'

class ameratream
    """estion de flu vidàÂ©o depuis camàÂ©ras """
    
    def __init__(self, camera_url str, buffer_size int  )
        """
        nitialise une conneion àÂ  un flu camàÂ©ra.
        
        rgs
            camera_url  de la camàÂ©ra (, , etc.)
            buffer_size aille du buffer de frames
        """
        self.camera_url  camera_url
        self.is_running  alse
        self.frame_buffer  queue.ueue(masizebuffer_size)
        self.lock  threading.ock()
        self.capture  one
        self.thread  one
        self.last_frame  one
        self.last_error  one
        self.reconnect_delay    # secondes
        self.ma_reconnect_attempts  
        
    def start(self) - bool
        """
        àÂ©marre la capture du flu camàÂ©ra dans un thread sàÂ©paràÂ©.
        
        eturns
            rue si dàÂ©marràÂ© avec succàÂ¨s, alse sinon
        """
        with self.lock
            if self.is_running
                return rue
                
            self.is_running  rue
            self.thread  threading.hread(
                targetself._capture_loop,
                daemonrue
            )
            self.thread.start()
            
            # ttendre que le premier frame soit disponible ou qu'une erreur survienne
            timeout    # secondes
            start_time  time.time()
            
            while time.time() - start_time  timeout
                if not self.frame_buffer.empty() or self.last_error
                    break
                time.sleep(.)
                
            return not self.frame_buffer.empty()
    
    def stop(self)
        """rràÂªte la capture du flu camàÂ©ra"""
        with self.lock
            self.is_running  alse
            
            if self.thread and self.thread.is_alive()
                self.thread.join(timeout)
                
            if self.capture
                self.capture.release()
                self.capture  one
                
            # ider le buffer
            while not self.frame_buffer.empty()
                try
                    self.frame_buffer.get_nowait()
                ecept queue.mpty
                    break
    
    def get_frame(self) -> Tuple[bool, Optional[Any]]:
        """
        àÂ©cupàÂ¨re le dernier frame du buffer.
        
        eturns
            (success, frame) uple indiquant si un frame est disponible et le frame lui-màÂªme
        """
        try
            if not self.frame_buffer.empty()
                frame  self.frame_buffer.get_nowait()
                self.last_frame  frame
                return rue, frame
            elif self.last_frame is not one
                return rue, self.last_frame
            else
                return alse, one
        ecept ception as e
            logger.error(f"rreur lors de la ràÂ©cupàÂ©ration du frame {e}")
            return alse, one
    
    def _capture_loop(self)
        """oucle principale de capture des frames"""
        reconnect_attempts  
        
        while self.is_running
            try
                if self.capture is one or not self.capture.ispened()
                    # nitialiser ou ràÂ©initialiser la capture
                    if self.capture
                        self.capture.release()
                    self.capture  cv.ideoapture(self.camera_url)
                    if not self.capture.ispened()
                        reconnect_attempts + 
                        self.last_error  (
                            f"mpossible d'ouvrir la camàÂ©ra {self.camera_url}"
                        )
                        logger.warning(
                            f"{self.last_error} (tentative {reconnect_attempts}/"
                            f"{self.ma_reconnect_attempts})"
                        )
                        
                        if reconnect_attempts  self.ma_reconnect_attempts
                            logger.error(f"bandon apràÂ¨s {reconnect_attempts} tentatives")
                            self.is_running  alse
                            break
                            
                        time.sleep(self.reconnect_delay)
                        continue
                    else
                        reconnect_attempts  
                        logger.info(f"onneion àÂ©tablie au flu {self.camera_url}")
                
                # ire un frame
                ret, frame  self.capture.read()
                
                if not ret
                    logger.warning(f"rreur de lecture du frame depuis {self.camera_url}")
                    time.sleep(.)
                    continue
                
                # ettre le frame dans le buffer (en àÂ©crasant le plus ancien si plein)
                if self.frame_buffer.full()
                    try
                        self.frame_buffer.get_nowait()
                    ecept queue.mpty
                        pass
                        
                self.frame_buffer.put(frame)
                
            ecept ception as e
                logger.error(f"rreur dans la boucle de capture {e}")
                time.sleep()
        
        # ettoyage final
        if self.capture
            self.capture.release()
            self.capture  one

class ecordingask
    """epràÂ©sente une tàÂ¢che d'enregistrement vidàÂ©o"""
    
    def __init__(self, session_id str, camera_url str, output_path str, 
                 ma_duration int, user_id int, court_id int,
                 session_name str, video_quality ictstr, ny])
        """
        nitialise une tàÂ¢che d'enregistrement.
        
        rgs
            session_id dentifiant unique de la session
            camera_url  de la camàÂ©ra
            output_path hemin du fichier de sortie
            ma_duration uràÂ©e maimale en secondes
            user_id  de l'utilisateur
            court_id  du terrain
            session_name om de la session
            video_quality aramàÂ¨tres de qualitàÂ© vidàÂ©o
        """
        self.session_id  session_id
        self.camera_url  camera_url
        self.output_path  output_path
        self.ma_duration  ma_duration
        self.user_id  user_id
        self.court_id  court_id
        self.session_name  session_name
        self.video_quality  video_quality
        
        self.start_time  datetime.now()
        self.status  'created'
        self.process  one
        self.camera_stream  one
        self.error  one
        self.file_size  
        
    def to_dict(self) - ictstr, ny]
        """
        onvertit l'objet en dictionnaire.
        
        eturns
            ictionnaire des attributs de la tàÂ¢che
        """
        duration  int((datetime.now() - self.start_time).total_seconds())
        
        return {
            'session_id' self.session_id,
            'camera_url' self.camera_url,
            'output_path' self.output_path,
            'status' self.status,
            'start_time' self.start_time.isoformat(),
            'duration' duration,
            'user_id' self.user_id,
            'court_id' self.court_id,
            'session_name' self.session_name,
            'file_size' self.file_size,
            'error' self.error
        }

class ideoaptureervice
    """ervice optimisàÂ© de capture vidàÂ©o pour camàÂ©ras  et enregistrements fiables"""
    
    def __init__(self, base_path str  "static/videos")
        """
        nitialise le service de capture vidàÂ©o.
        
        rgs
            base_path hemin de base pour le stockage des vidàÂ©os
        """
        # onfiguration des chemins
        self.base_path  ath(base_path)
        self.base_path.mkdir(parentsrue, eist_okrue)
        
        self.thumbnails_path  ath("static/thumbnails")
        self.thumbnails_path.mkdir(parentsrue, eist_okrue)
        
        self.temp_path  ath("static/temp")
        self.temp_path.mkdir(parentsrue, eist_okrue)
        
        # --- ouveau configuration modes & limites ---
        self.recording_mode  os.getenv('_', 'single').lower()  # 'single' | 'segmented'
        self.ma_concurrent_recordings  int(os.getenv('__', ''))
        if self.recording_mode not in ('single', 'segmented')
            logger.warning(f"ode _ invalide {self.recording_mode}, fallback 'single'")
            self.recording_mode  'single'
        logger.info(f"à°ÂÂÂà¯Â¸Â ode d'enregistrement  {self.recording_mode}")
        logger.info(f"à°ÂÂÂà¯Â¸Â imite enregistrements concurrents {self.ma_concurrent_recordings}")
        # ------------------------------------------------
        
        # estion des enregistrements
        self.recordings ictstr, ecordingask]  {}
        self.recording_processes ictstr, subprocess.open]  {}
        self.camera_streams ictstr, ameratream]  {}
        
        # estionnaire  pour unny tream
        self.mjpeg_manager  ecordinganager(ecordingonfig())
        
        # errou pour la synchronisation des accàÂ¨s concurrents
        self.lock  threading.ock()
        
        # onfiguration d'encodage
        self.ma_recording_duration    #  heure ma
        self.video_quality  {
            'fps' ,
            'width' ,
            'height' ,
            'bitrate' '',
            'preset' 'veryfast',  # ptions ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow
            'tune' 'zerolatency'  # ptimisàÂ© pour le streaming temps ràÂ©el
        }
        
        # ool de threads pour les tàÂ¢ches asynchrones
        self.thread_pool  hreadoolecutor(ma_workers)
        
        # àÂ©marrer le thread de surveillance
        self.monitoring_thread  threading.hread(
            targetself._monitoring_loop,
            daemonrue
        )
        self.monitoring_thread.start()
        
        logger.info("✅"
 ervice de capture vidàÂ©o initialisàÂ© avec succàÂ¨s")
    
    def start_recording(self, court_id int, user_id int, session_name str  one, session_id str | one  one) - ictstr, ny]
        """
        àÂ©marre l'enregistrement d'un terrain.
        eut accepter un session_id eterne pour aligner les identifiants (ecordingession).
        
        rgs
            court_id  du terrain àÂ  enregistrer
            user_id  de l'utilisateur qui dàÂ©marre l'enregistrement
            session_name om de la session (optionnel)
            session_id dentifiant de session eterne (optionnel)
            
        eturns
            nformations sur la session d'enregistrement dàÂ©marràÂ©e
        
        aises
            aluerror i les paramàÂ¨tres sont invalides
            untimerror i l'enregistrement ne peut pas dàÂ©marrer
        """
        # àÂ ràÂ©implantation complàÂ¨te avec gàÂ©nàÂ©ration s, tàÂ¢che et sàÂ©lection du mode
        with self.lock
            try
                court  self._validate_court(court_id)
                user  self._validate_user(user_id)
                for rec in self.recordings.values()
                    if rec.court_id  court_id
                        raise untimerror(f"n enregistrement est dàÂ©jàÂ  actif sur le terrain {court_id}")
                if len(self.recordings)  self.ma_concurrent_recordings
                    raise untimerror("imite d'enregistrements concurrents atteinte")
                # tiliser l' fourni sinon en gàÂ©nàÂ©rer un
                if session_id is one
                    session_id  f"rec_{court_id}_{int(time.time())}_{uuid.uuid().he]}"
                if not session_name
                    session_name  f"atch du {datetime.now().strftime('%d/%m/%')}"
                video_filename  f"{session_id}.mp"
                video_path  str(self.base_path / video_filename)
                camera_url  self._get_camera_url(court)
                recording_task  ecordingask(
                    session_idsession_id,
                    camera_urlcamera_url,
                    output_pathvideo_path,
                    ma_durationself.ma_recording_duration,
                    user_iduser_id,
                    court_idcourt_id,
                    session_namesession_name,
                    video_qualityself.video_quality
                )
                if self._is_mjpeg_url(camera_url)
                    if self.recording_mode  'segmented'
                        success  self._start_mjpeg_recording_segmented(recording_task)
                    else
                        success  self._start_mjpeg_recording_single(recording_task)
                elif self._is_rtsp_url(camera_url)
                    success  self._start_ffmpeg_recording(recording_task)
                else
                    success  self._start_opencv_recording(recording_task)
                if not success
                    raise untimerror(f"mpossible de dàÂ©marrer l'enregistrement pour le terrain {court_id}")
                self.recordingssession_id]  recording_task
                logger.info(f"à°ÂÂÂ¬ nregistrement dàÂ©marràÂ© {session_id} pour terrain {court_id}")
                return {
                    'session_id' session_id,
                    'status' 'started',
                    'message' f"nregistrement dàÂ©marràÂ© pour {session_name}",
                    'video_filename' video_filename,
                    'camera_url' camera_url,
                    'recording_type' getattr(recording_task, 'recording_type', 'standard')
                }
            ecept ception as e
                logger.error(f"à¢ÂÂ rreur lors du dàÂ©marrage de l'enregistrement {e}")
                if 'session_id' in locals()
                    self._cleanup_recording(session_id)
                raise
    
    def stop_recording(self, session_id str) - ictstr, ny]
        """
        rràÂªte l'enregistrement d'une session.
        
        rgs
            session_id dentifiant de la session àÂ  arràÂªter
            
        eturns
            nformations sur la session arràÂªtàÂ©e
            
        aises
            aluerror i la session n'eiste pas
        """
        with self.lock
            if session_id not in self.recordings
                return {
                    'status' 'error',
                    'error' f"ession {session_id} non trouvée",
                    'message' "nregistrement introuvable ou dàÂ©jàÂ  terminàÂ©"
                }
            
            recording  self.recordingssession_id]
            recording.status  'stopping'
            if hasattr(recording, 'recording_type') and recording.recording_type  'mjpeg_single'
                logger.debug(f"rràÂªt  single {session_id}")
            # rocess handling
            if session_id in self.recording_processes
                process  self.recording_processessession_id]
                try
                    self._graceful_stop_ffmpeg(process, session_id)
                finally
                    if process.poll() is one
                        try
                            process.terminate() process.wait(timeout)
                        ecept ception
                            try process.kill()
                            ecept ception pass
                    eit_code  process.returncode
                    del self.recording_processessession_id]
                    logger.info(f"mpeg terminàÂ© pour {session_id} code{eit_code}")
            # top camera stream
            if session_id in self.camera_streams
                self.camera_streamssession_id].stop() del self.camera_streamssession_id]
        # inalize outside lock
        result  self._finalize_recording(session_id)
        with self.lock
            if session_id in self.recordings
                del self.recordingssession_id]
        logger.info(f"à¢ÂÂ¹à¯Â¸Â nregistrement arràÂªtàÂ© {session_id} - {result.get('status')} taille{self._get_file_size(recording.output_path)}")
        return result

    def _get_file_size(self, file_path str) - int
        try
            return os.path.getsize(file_path)
        ecept ception
            return 

    def _generate_thumbnail(self, video_path str, session_id str) - bool
        """àÂ©nàÂ¨re une miniature àÂ  ~s (fallback pen si ffmpeg àÂ©choue)."""
        try
            thumb_path  self.thumbnails_path / f"{session_id}.jpg"
            # ssayer avec ffmpeg
            cmd  
                _,
                '-y',
                '-ss', '',  # position approimative
                '-i', video_path,
                '-vframes', '',
                '-vf', 'scale-',
                str(thumb_path)
            ]
            proc  subprocess.run(cmd, stdoutsubprocess., stderrsubprocess., timeout)
            if proc.returncode   and thumb_path.eists() and thumb_path.stat().st_size  
                return rue
            logger.warning(f"allback pen thumbnail (ffmpeg code{proc.returncode})")
        ecept ception as fe
            logger.warning(f"humbnail ffmpeg àÂ©chec {fe}")
        # allback pen
        try
            cap  cv.ideoapture(video_path)
            if not cap.ispened()
                return alse
            cap.set(cv.___, )  # s
            ret, frame  cap.read()
            cap.release()
            if not ret or frame is one
                return alse
            cv.imwrite(str(self.thumbnails_path / f"{session_id}.jpg"), frame)
            return rue
        ecept ception as oe
            logger.error(f"humbnail pen àÂ©chec {oe}")
            return alse

    def _stretch_video_duration(self, src_path str, ratio float) - tuplebool, float, str]
        """àÂtire la duràÂ©e vidàÂ©o (ralentit) via setpts si ratio.
        etourne (success, new_duration, new_path)."""
        try
            if ratio  .
                return alse, ., src_path
            # imiter ratio pour àÂ©viter valeurs etràÂªmes
            ratio  min(ratio, .)
            tmp_path  str(ath(src_path).with_suffi('.stretch.tmp.mp'))
            cmd  
                _,
                '-hide_banner','-loglevel','error',
                '-i', src_path,
                '-an',  # pas d'audio
                '-filterv', f'setpts{ratio}*',
                '-movflags', '+faststart',
                '-preset', 'veryfast',
                '-crf', '',
                tmp_path
            ]
            logger.info(f"à°ÂÂÂ à¯Â¸Â àÂtirement vidàÂ©o ratio{ratio.f} cmd{' '.join(cmd)}")
            proc  subprocess.run(cmd, stdoutsubprocess., stderrsubprocess., universal_newlinesrue, timeout)
            if proc.returncode !  or not os.path.eists(tmp_path)
                logger.error(f"àÂchec àÂ©tirement vidàÂ©o code{proc.returncode} err{proc.stderr]}")
                return alse, ., src_path
            # robe nouvelle duràÂ©e
            new_dur  one
            try
                probe  subprocess.run(_,'-v','error','-select_streams','v','-show_entries','streamduration','-of','defaultnoprint_wrappers',tmp_path],stdoutsubprocess.,stderrsubprocess.,universal_newlinesrue,timeout)
                if probe.returncode
                    for line in probe.stdout.splitlines()
                        if line.startswith('duration')
                            try new_durfloat(line.split('')])
                            ecept pass
            ecept ception
                pass
            if new_dur is one
                new_dur  .
            # emplacer fichier source (backup facultative)
            backup_path  src_path + '.orig'
            try
                os.replace(src_path, backup_path)
                os.replace(tmp_path, src_path)
            ecept ception as rep_e
                logger.error(f"emplacement fichier àÂ©chouàÂ© {rep_e}")
                return alse, ., src_path
            # arder backup pour debug (peut àÂªtre nettoyàÂ© plus tard)
            logger.info(f"✅"
 àÂtirement terminàÂ© nouvelle_duràÂ©eà¢ÂÂ{new_dur.f}s (ratio demandàÂ© {ratio.f})")
            return rue, new_dur, backup_path
        ecept ception as e
            logger.error(f"rreur stretch vidàÂ©o {e}")
            return alse, ., src_path

    def _finalize_recording(self, session_id str) - ictstr, ny]
        """inalise l'enregistrement et cràÂ©e l'entràÂ©e en base (tolàÂ©rant si ffprobe absent)."""
        try
            recording  self.recordingssession_id]
            if not os.path.eists(recording.output_path)
                return {'status''error','error'f"ichier vidàÂ©o non trouvé {recording.output_path}", 'message''inalisation impossible'}
            duration_seconds  one
            nb_frames  one
            probe_ok  alse
            try
                probe_cmd  
                    _,
                    '-v','error',
                    '-select_streams','v',
                    '-show_entries','streamduration,nb_frames',
                    '-of','defaultnoprint_wrappers',
                    recording.output_path
                ]
                probe  subprocess.run(probe_cmd, stdoutsubprocess., stderrsubprocess., universal_newlinesrue, timeout)
                probe_ok  probe.returncode  
                if probe_ok
                    for line in probe.stdout.splitlines()
                        if line.startswith('duration')
                            try duration_seconds  float(line.split('')])
                            ecept pass
                        elif line.startswith('nb_frames')
                            try nb_frames  int(line.split('')])
                            ecept pass
                else
                    if 'moov atom not found' in probe.stderr.lower()
                        logger.error(f"à¢ÂÂ moov absent {session_id}")
            ecept ileotoundrror
                logger.warning("ffprobe introuvable - fallback estimation duràÂ©e")
            ecept ception as pe
                logger.warning(f"robe àÂ©chec {pe}")
            file_size  self._get_file_size(recording.output_path)
            wallclock_secs  (datetime.now()-recording.start_time).total_seconds()
            if duration_seconds is one
                duration_seconds  ma(, int(wallclock_secs))
            target_fps  self.video_quality.get('fps',)
            est_from_frames  (nb_frames/target_fps) if (nb_frames and target_fps) else one
            if est_from_frames and abs(est_from_frames - wallclock_secs)  
                logger.warning(
                    f"à¢ÂÂ±à¯Â¸Â cart duràÂ©e wallclock{wallclock_secs.f}s ffprobe{duration_seconds.f}s frames_est{est_from_frames.f}s nb_frames{nb_frames}")
            # àÂtirement si ratio important (.) et frames_est proche duràÂ©e actuelle (indiquant timestamps compressàÂ©s)
            stretched  alse
            backup_path  one
            if wallclock_secs   and duration_seconds   and wallclock_secs/duration_seconds  .
                ratio  wallclock_secs / duration_seconds
                ok, new_dur, backup_path  self._stretch_video_duration(recording.output_path, ratio)
                if ok and new_dur  duration_seconds
                    duration_seconds  new_dur
                    stretched  rue
            # eprobe apràÂ¨s àÂ©ventuel stretch (duràÂ©e plus pràÂ©cise)
            if stretched
                try
                    probe  subprocess.run(
                        _,'-v','error','-select_streams','v','-show_entries','streamduration','-of','defaultnoprint_wrappers',recording.output_path
                    ],stdoutsubprocess.,stderrsubprocess.,universal_newlinesrue,timeout)
                    if probe.returncode
                        for line in probe.stdout.splitlines()
                            if line.startswith('duration')
                                try duration_secondsfloat(line.split('')])
                                ecept pass
                ecept ception
                    pass
            # ejet si fichier tràÂ¨s court avant cràÂ©ation 
            if duration_seconds   or file_size  *
                return {'status''error','error''ichier incomplet','file_size'file_size,'duration'duration_seconds,'nb_frames'nb_frames}
            thumb  self._generate_thumbnail(recording.output_path, recording.session_id)
            video  ideo(
                titlerecording.session_name,
                file_urlf"/videos/{os.path.basename(recording.output_path)}",
                thumbnail_urlf"/thumbnails/{recording.session_id}.jpg" if thumb else one,
                durationint(duration_seconds),
                file_sizefile_size,
                court_idrecording.court_id,
                user_idrecording.user_id,
                recorded_atrecording.start_time,
                is_unlockedalse,
                credits_cost,
            )
            db.session.add(video) db.session.commit()
            logger.info(
                f"✅"
 idàÂ©o validàÂ©e {video.id} dur{duration_seconds.f}s wallclock{wallclock_secs.f}s nb_frames{nb_frames} taille{file_size} stretched{stretched}")
            return {
                'status''completed',
                'video_id'video.id,
                'video_filename'os.path.basename(recording.output_path),
                'duration'int(duration_seconds),
                'wallclock_duration'int(wallclock_secs),
                'nb_frames'nb_frames,
                'file_size'file_size,
                'thumbnail_url'video.thumbnail_url,
                'stretched' stretched,
                'original_backup' backup_path if stretched else one
            }
        ecept ception as e
            logger.error(f"à¢ÂÂ inalisation erreur {e}")
            return {'status''error','error'str(e)}
    
    def test_camera_connection(self, camera_url str) - ictstr, ny]
        """
        este la conneion àÂ  une camàÂ©ra.
        
        rgs
            camera_url  de la camàÂ©ra àÂ  tester
            
        eturns
            àÂ©sultat du test
        """
        try
            logger.info(f"à°ÂÂÂ est de conneion àÂ  la camàÂ©ra {camera_url}")
            
            # ràÂ©er un stream de camàÂ©ra temporaire
            camera  ameratream(camera_url)
            
            # ssayer de dàÂ©marrer et récupérer un frame
            start_success  camera.start()
            frame_success  alse
            resolution  one
            
            if start_success
                # ttendre un peu pour avoir des frames
                time.sleep()
                
                # ssayer de récupérer un frame
                success, frame  camera.get_frame()
                frame_success  success
                
                if success and frame is not one
                    height, width  frame.shape]
                    resolution  {"width" width, "height" height}
            
            # rràÂªter proprement
            camera.stop()
            
            return {
                'status' 'success' if start_success and frame_success else 'error',
                'connection' start_success,
                'frames_available' frame_success,
                'resolution' resolution,
                'error' camera.last_error,
                'url' camera_url
            }
            
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur lors du test de la camàÂ©ra {e}")
            return {
                'status' 'error',
                'connection' alse,
                'frames_available' alse,
                'error' str(e),
                'url' camera_url
            }
    
    # ------ àÂ©thodes privàÂ©es ------
    
    def _validate_court(self, court_id int) - ourt
        """alide et ràÂ©cupàÂ¨re un terrain"""
        court  ourt.query.get(court_id)
        if not court
            raise aluerror(f"errain {court_id} non trouvé")
        return court
    
    def _validate_user(self, user_id int) - ser
        """alide et ràÂ©cupàÂ¨re un utilisateur"""
        user  ser.query.get(user_id)
        if not user
            raise aluerror(f"tilisateur {user_id} non trouvé")
        return user
    
    def _get_camera_url(self, court ourt) - str
        """àÂ©cupàÂ¨re l' de la camàÂ©ra pour un terrain"""
        if hasattr(court, 'camera_url') and court.camera_url
            return court.camera_url
        else
            #  de simulation pour les tests
            return f"http//localhost/api/courts/{court.id}/camera_stream"
    
    def _is_rtsp_url(self, url str) - bool
        """àÂ©termine si l' est un flu """
        return url.lower().startswith(('rtsp//', 'rtsps//'))
    
    def _is_mjpeg_url(self, url str) - bool
        """àÂ©termine si l' est un flu """
        url_lower  url.lower()
        return (url_lower.endswith(('.mjpg', '.mjpeg', '.cgi')) or 
                'mjpg' in url_lower or 'mjpeg' in url_lower)
    
    def _start_mjpeg_recording_segmented(self, recording ecordingask) - bool
        """ncien mode segmentàÂ© utilise ecordinganager (upload par segments)."""
        try
            result  self.mjpeg_manager.start_recording(
                recording_idrecording.session_id,
                mjpeg_urlrecording.camera_url,
                session_namerecording.session_name,
                segment_duration  # configurable via futur env si besoin
            )
            recording.recording_type  'mjpeg_bunny'
            recording.bunny_session_id  result'session_id']
            recording.status  'recording'
            recording.start_time  datetime.now()
            logger.info(f"à°ÂÂÂ¬ (egmented) nregistrement  dàÂ©marràÂ© vers unny {recording.session_id}")
            return rue
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur dàÂ©marrage  segmentàÂ© {e}")
            recording.status  'error'
            recording.error  str(e)
            return alse

    def _spawn_ffmpeg_process(self, cmd list, session_id str)
        """ance mpeg avec stdin  pour pouvoir envoyer 'q' et lit stderr en arriàÂ¨re-plan.
        mpàÂªche le blocage des pipes (memory leak) et permet un arràÂªt propre àÂ©crivant l'atome moov."""
        process  subprocess.open(
            cmd,
            stdinsubprocess.,
            stdoutsubprocess.,
            stderrsubprocess.,
            universal_newlinesrue,
            bufsize
        )
        # hread lecteur stderr (àÂ©vite remplissage buffer)
        def _drain()
            try
                for line in process.stderr
                    if not line
                        break
                    if 'frame' in line or 'fps' in line
                        continue  # trop verbeu
                    logger.debug(f"mpeg{session_id}] {line.strip()}")
            ecept ception
                pass
        t  threading.hread(target_drain, daemonrue)
        t.start()
        return process

    def _graceful_stop_ffmpeg(self, process subprocess.open, session_id str)
        """ente un arràÂªt dou (envoie 'q') pour que mpeg àÂ©crive la fin du conteneur ."""
        if process.poll() is not one
            return
        try
            if process.stdin
                try
                    process.stdin.write('q')
                    process.stdin.flush()
                ecept ception
                    pass
            # ttendre àÂ©criture trailer
            process.wait(timeout)
        ecept subprocess.imeoutpired
            try
                process.terminate()  # indows erminaterocess
                process.wait(timeout)
            ecept ception
                try
                    process.kill()
                ecept ception
                    pass

    def _start_mjpeg_recording_single(self, recording ecordingask) - bool
        """àÂ©marre un enregistrement  (mode single) avec cadence temps ràÂ©el corrigàÂ©e.
        justements
          - àÂ©placer le framerate en option 'àÂ (-framerate) avant -i pour que mpeg gàÂ©nàÂ¨re des timestamps espacàÂ©s
          - etirer combo '-vsync cfr -r fps' en sortie qui compressait le temps lorsque les frames arrivaient en rafale
          - onserver -re pour limiter la lecture si applicable
        """
        try
            target_fps  str(self.video_quality.get('fps', ))
            ffmpeg_cmd  
                _,
                '-hide_banner', '-loglevel', 'info',
                '-re',
                '-f', 'mjpeg',
                '-reconnect', '', '-reconnect_streamed', '', '-reconnect_delay_ma', '',
                '-thread_queue_size', '',
                '-framerate', target_fps,  # (-  option d'entràÂ©e)
                '-i', recording.camera_url,
                '-fflags', '+genpts',
                '-use_wallclock_as_timestamps', '',
                # ortie sans forcer vsync/r de nouveau laisser ffmpeg utiliser le framerate d'entràÂ©e
                '-cv', 'lib',
                '-preset', self.video_quality'preset'],
                '-tune', 'zerolatency',
                '-pi_fmt', 'yuvp',
                '-profilev', 'main',
                '-movflags', '+faststart',
                '-crf', '',
                '-g', str(int(target_fps) * ),
                '-an',
                recording.output_path
            ]
            logger.info(f"à°ÂÂÂ¬ (ingle) mpeg  cmd {' '.join(ffmpeg_cmd)}")
            process  self._spawn_ffmpeg_process(ffmpeg_cmd, recording.session_id)
            if process.poll() is not one
                raise untimerror('mpeg non dàÂ©marràÂ©')
            self.recording_processesrecording.session_id]  process
            recording.status  'recording'
            recording.process  process
            recording.recording_type  'mjpeg_single'
            recording.start_time  datetime.now()
            threading.imer(self.ma_recording_duration, lambda self._auto_timeout_stop(recording.session_id)).start()
            return rue
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur dàÂ©marrage  single {e}")
            recording.status  'error'
            recording.error  str(e)
            return alse
    def _start_ffmpeg_recording(self, recording ecordingask) - bool
        """àÂ©marre un enregistrement avec mpeg ()."""
        try
            ffmpeg_cmd  
                _,
                '-rtsp_transport', 'tcp',
                '-i', recording.camera_url,
                '-cv', 'lib',
                '-preset', self.video_quality'preset'],
                '-tune', self.video_quality'tune'],
                '-crf', '',
                '-ca', 'aac', '-ba', 'k',
                '-movflags', '+faststart',
                recording.output_path
            ]
            logger.info(f"à°ÂÂÂ¬ àÂ©marrage mpeg  {recording.session_id}")
            process  self._spawn_ffmpeg_process(ffmpeg_cmd, recording.session_id)
            if process.poll() is not one
                raise untimerror("mpeg n'a pas pu dàÂ©marrer")
            self.recording_processesrecording.session_id]  process        
            recording.status  'recording'
            recording.process  process
            recording.recording_type  'rtsp'
            recording.start_time  datetime.now()
            threading.imer(
                self.ma_recording_duration,
                lambda self._auto_timeout_stop(recording.session_id)
            ).start()
            return rue
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur lors du dàÂ©marrage de mpeg {e}")
            recording.status  'error'
            recording.error  str(e)
            return alse
    
    def _start_opencv_recording(self, recording ecordingask) - bool
        """àÂ©marre un enregistrement avec pen"""
        try
            # ràÂ©er un stream camàÂ©ra
            camera  ameratream(recording.camera_url)
            
            # ssayer de dàÂ©marrer et récupérer un frame
            start_success  camera.start()
            frame_success  alse
            resolution  one
            
            if start_success
                # ttendre un peu pour avoir des frames
                time.sleep()
                
                # ssayer de récupérer un frame
                success, frame  camera.get_frame()
                frame_success  success
                
                if success and frame is not one
                    height, width  frame.shape]
                    resolution  {"width" width, "height" height}
            
            if not start_success
                raise untimerror(f"mpossible de dàÂ©marrer la capture pour {recording.camera_url}")
            
            # nregistrer le stream
            recording.camera_stream  camera
            recording.status  'recording'
            recording.recording_type  'opencv'
            recording.start_time  datetime.now()
            
            # ancer le thread d'enregistrement pen
            record_thread  threading.hread(
                targetself._opencv_recording_thread,
                args(recording.session_id, recording),
                daemonrue
            )
            record_thread.start()
            
            # imer auto-stop sàÂ©curitàÂ©
            threading.imer(
                self.ma_recording_duration,
                lambda self._auto_timeout_stop(recording.session_id)
            ).start()
            
            return rue
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur lors du dàÂ©marrage d'pen {e}")
            recording.status  'error'
            recording.error  str(e)
            return alse
    
    def _opencv_recording_thread(self, session_id str, recording ecordingask)
        """hread d'enregistrement vidàÂ©o avec pen"""
        try
            camera  self.camera_streams.get(session_id)    
            if not camera
                raise untimerror(f"tream camàÂ©ra non trouvé pour {session_id}")
            
            # àÂ©cupàÂ©rer un premier frame pour obtenir les dimensions    
            success, frame  camera.get_frame()
            if not success or frame is one
                raise untimerror("mpossible d'obtenir le premier frame")
            
            height, width  frame.shape]
            fps  self.video_quality'fps']
            
            # onfiguration de l'encodeur
            fourcc  cv.ideoriter_fourcc(*'mpv')
            out  cv.ideoriter(recording.output_path, fourcc, fps, (width, height))
            
            start_time  time.time()
            frame_count  
            last_frame_time  start_time
            
            while rue
                # àÂ©rifier si on doit s'arràÂªter
                with self.lock
                    if session_id not in self.recordings or self.recordingssession_id].status  'stopping'
                        break
                
                # àÂ©cupàÂ©rer un frame
                success, frame  camera.get_frame()
                if not success or frame is one
                    time.sleep(.)  # ause courte pour àÂ©viter  %
                    continue
                
                # àÂcrire le frame
                out.write(frame)
                frame_count + 
                
                # especter le  cible
                current_time  time.time()
                target_time  last_frame_time + (. / fps)
                if current_time  target_time
                    time.sleep(target_time - current_time)
                
                last_frame_time  time.time()
            
            # ettoyer les ressources
            out.release()
            logger.info(f"✅"
 nregistrement pen terminàÂ© {session_id}, {frame_count} frames")
            
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur dans le thread pen pour {session_id} {e}")
            with self.lock
                if session_id in self.recordings
                    self.recordingssession_id].status  'error'
                    self.recordingssession_id].error  str(e)
    
    def _auto_timeout_stop(self, session_id str)
        with self.lock
            if session_id in self.recordings and 
               self.recordingssession_id].status  'recording'
                logger.warning(f"à¢ÂÂ±à¯Â¸Â uto-stop (duràÂ©e ma atteinte) session {session_id}")
                try
                    self.stop_recording(session_id)
                ecept ception as e
                    logger.error(f"rreur auto-stop {e}")

    def _finalize_recording(self, session_id str) - ictstr, ny]
        """inalise l'enregistrement et cràÂ©e l'entràÂ©e en base (tolàÂ©rant si ffprobe absent)."""
        try
            recording  self.recordingssession_id]
            if not os.path.eists(recording.output_path)
                return {'status''error','error'f"ichier vidàÂ©o non trouvé {recording.output_path}", 'message''inalisation impossible'}
            duration_seconds  one
            nb_frames  one
            probe_ok  alse
            try
                probe_cmd  
                    _,
                    '-v','error',
                    '-select_streams','v',
                    '-show_entries','streamduration,nb_frames',
                    '-of','defaultnoprint_wrappers',
                    recording.output_path
                ]
                probe  subprocess.run(probe_cmd, stdoutsubprocess., stderrsubprocess., universal_newlinesrue, timeout)
                probe_ok  probe.returncode  
                if probe_ok
                    for line in probe.stdout.splitlines()
                        if line.startswith('duration')
                            try duration_seconds  float(line.split('')])
                            ecept pass
                        elif line.startswith('nb_frames')
                            try nb_frames  int(line.split('')])
                            ecept pass
                else
                    if 'moov atom not found' in probe.stderr.lower()
                        logger.error(f"à¢ÂÂ moov absent {session_id}")
            ecept ileotoundrror
                logger.warning("ffprobe introuvable - fallback estimation duràÂ©e")
            ecept ception as pe
                logger.warning(f"robe àÂ©chec {pe}")
            file_size  self._get_file_size(recording.output_path)
            wallclock_secs  (datetime.now()-recording.start_time).total_seconds()
            if duration_seconds is one
                duration_seconds  ma(, int(wallclock_secs))
            target_fps  self.video_quality.get('fps',)
            est_from_frames  (nb_frames/target_fps) if (nb_frames and target_fps) else one
            if est_from_frames and abs(est_from_frames - wallclock_secs)  
                logger.warning(
                    f"à¢ÂÂ±à¯Â¸Â cart duràÂ©e wallclock{wallclock_secs.f}s ffprobe{duration_seconds.f}s frames_est{est_from_frames.f}s nb_frames{nb_frames}")
            # àÂtirement si ratio important (.) et frames_est proche duràÂ©e actuelle (indiquant timestamps compressàÂ©s)
            stretched  alse
            backup_path  one
            if wallclock_secs   and duration_seconds   and wallclock_secs/duration_seconds  .
                ratio  wallclock_secs / duration_seconds
                ok, new_dur, backup_path  self._stretch_video_duration(recording.output_path, ratio)
                if ok and new_dur  duration_seconds
                    duration_seconds  new_dur
                    stretched  rue
            # eprobe apràÂ¨s àÂ©ventuel stretch (duràÂ©e plus pràÂ©cise)
            if stretched
                try
                    probe  subprocess.run(
                        _,'-v','error','-select_streams','v','-show_entries','streamduration','-of','defaultnoprint_wrappers',recording.output_path
                    ],stdoutsubprocess.,stderrsubprocess.,universal_newlinesrue,timeout)
                    if probe.returncode
                        for line in probe.stdout.splitlines()
                            if line.startswith('duration')
                                try duration_secondsfloat(line.split('')])
                                ecept pass
                ecept ception
                    pass
            # ejet si fichier tràÂ¨s court avant cràÂ©ation 
            if duration_seconds   or file_size  *
                return {'status''error','error''ichier incomplet','file_size'file_size,'duration'duration_seconds,'nb_frames'nb_frames}
            thumb  self._generate_thumbnail(recording.output_path, recording.session_id)
            video  ideo(
                titlerecording.session_name,
                file_urlf"/videos/{os.path.basename(recording.output_path)}",
                thumbnail_urlf"/thumbnails/{recording.session_id}.jpg" if thumb else one,
                durationint(duration_seconds),
                file_sizefile_size,
                court_idrecording.court_id,
                user_idrecording.user_id,
                recorded_atrecording.start_time,
                is_unlockedalse,
                credits_cost,
            )
            db.session.add(video) db.session.commit()
            logger.info(
                f"✅"
 idàÂ©o validàÂ©e {video.id} dur{duration_seconds.f}s wallclock{wallclock_secs.f}s nb_frames{nb_frames} taille{file_size} stretched{stretched}")
            return {
                'status''completed',
                'video_id'video.id,
                'video_filename'os.path.basename(recording.output_path),
                'duration'int(duration_seconds),
                'wallclock_duration'int(wallclock_secs),
                'nb_frames'nb_frames,
                'file_size'file_size,
                'thumbnail_url'video.thumbnail_url,
                'stretched' stretched,
                'original_backup' backup_path if stretched else one
            }
        ecept ception as e
            logger.error(f"à¢ÂÂ inalisation erreur {e}")
            return {'status''error','error'str(e)}
    
    def test_camera_connection(self, camera_url str) - ictstr, ny]
        """
        este la conneion àÂ  une camàÂ©ra.
        
        rgs
            camera_url  de la camàÂ©ra àÂ  tester
            
        eturns
            àÂ©sultat du test
        """
        try
            logger.info(f"à°ÂÂÂ est de conneion àÂ  la camàÂ©ra {camera_url}")
            
            # ràÂ©er un stream de camàÂ©ra temporaire
            camera  ameratream(camera_url)
            
            # ssayer de dàÂ©marrer et récupérer un frame
            start_success  camera.start()
            frame_success  alse
            resolution  one
            
            if start_success
                # ttendre un peu pour avoir des frames
                time.sleep()
                
                # ssayer de récupérer un frame
                success, frame  camera.get_frame()
                frame_success  success
                
                if success and frame is not one
                    height, width  frame.shape]
                    resolution  {"width" width, "height" height}
            
            # rràÂªter proprement
            camera.stop()
            
            return {
                'status' 'success' if start_success and frame_success else 'error',
                'connection' start_success,
                'frames_available' frame_success,
                'resolution' resolution,
                'error' camera.last_error,
                'url' camera_url
            }
            
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur lors du test de la camàÂ©ra {e}")
            return {
                'status' 'error',
                'connection' alse,
                'frames_available' alse,
                'error' str(e),
                'url' camera_url
            }
    
    # ------ àÂ©thodes privàÂ©es ------
    
    def _validate_court(self, court_id int) - ourt
        """alide et ràÂ©cupàÂ¨re un terrain"""
        court  ourt.query.get(court_id)
        if not court
            raise aluerror(f"errain {court_id} non trouvé")
        return court
    
    def _validate_user(self, user_id int) - ser
        """alide et ràÂ©cupàÂ¨re un utilisateur"""
        user  ser.query.get(user_id)
        if not user
            raise aluerror(f"tilisateur {user_id} non trouvé")
        return user
    
    def _get_camera_url(self, court ourt) - str
        """àÂ©cupàÂ¨re l' de la camàÂ©ra pour un terrain"""
        if hasattr(court, 'camera_url') and court.camera_url
            return court.camera_url
        else
            #  de simulation pour les tests
            return f"http//localhost/api/courts/{court.id}/camera_stream"
    
    def _is_rtsp_url(self, url str) - bool
        """àÂ©termine si l' est un flu """
        return url.lower().startswith(('rtsp//', 'rtsps//'))
    
    def _is_mjpeg_url(self, url str) - bool
        """àÂ©termine si l' est un flu """
        url_lower  url.lower()
        return (url_lower.endswith(('.mjpg', '.mjpeg', '.cgi')) or 
                'mjpg' in url_lower or 'mjpeg' in url_lower)
    
    def _start_mjpeg_recording_segmented(self, recording ecordingask) - bool
        """ncien mode segmentàÂ© utilise ecordinganager (upload par segments)."""
        try
            result  self.mjpeg_manager.start_recording(
                recording_idrecording.session_id,
                mjpeg_urlrecording.camera_url,
                session_namerecording.session_name,
                segment_duration  # configurable via futur env si besoin
            )
            recording.recording_type  'mjpeg_bunny'
            recording.bunny_session_id  result'session_id']
            recording.status  'recording'
            recording.start_time  datetime.now()
            logger.info(f"à°ÂÂÂ¬ (egmented) nregistrement  dàÂ©marràÂ© vers unny {recording.session_id}")
            return rue
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur dàÂ©marrage  segmentàÂ© {e}")
            recording.status  'error'
            recording.error  str(e)
            return alse

    def _spawn_ffmpeg_process(self, cmd list, session_id str)
        """ance mpeg avec stdin  pour pouvoir envoyer 'q' et lit stderr en arriàÂ¨re-plan.
        mpàÂªche le blocage des pipes (memory leak) et permet un arràÂªt propre àÂ©crivant l'atome moov."""
        process  subprocess.open(
            cmd,
            stdinsubprocess.,
            stdoutsubprocess.,
            stderrsubprocess.,
            universal_newlinesrue,
            bufsize
        )
        # hread lecteur stderr (àÂ©vite remplissage buffer)
        def _drain()
            try
                for line in process.stderr
                    if not line
                        break
                    if 'frame' in line or 'fps' in line
                        continue  # trop verbeu
                    logger.debug(f"mpeg{session_id}] {line.strip()}")
            ecept ception
                pass
        t  threading.hread(target_drain, daemonrue)
        t.start()
        return process

    def _graceful_stop_ffmpeg(self, process subprocess.open, session_id str)
        """ente un arràÂªt dou (envoie 'q') pour que mpeg àÂ©crive la fin du conteneur ."""
        if process.poll() is not one
            return
        try
            if process.stdin
                try
                    process.stdin.write('q')
                    process.stdin.flush()
                ecept ception
                    pass
            # ttendre àÂ©criture trailer
            process.wait(timeout)
        ecept subprocess.imeoutpired
            try
                process.terminate()  # indows erminaterocess
                process.wait(timeout)
            ecept ception
                try
                    process.kill()
                ecept ception
                    pass

    def _start_mjpeg_recording_single(self, recording ecordingask) - bool
        """àÂ©marre un enregistrement  (mode single) avec cadence temps ràÂ©el corrigàÂ©e.
        justements
          - àÂ©placer le framerate en option 'àÂ (-framerate) avant -i pour que mpeg gàÂ©nàÂ¨re des timestamps espacàÂ©s
          - etirer combo '-vsync cfr -r fps' en sortie qui compressait le temps lorsque les frames arrivaient en rafale
          - onserver -re pour limiter la lecture si applicable
        """
        try
            target_fps  str(self.video_quality.get('fps', ))
            ffmpeg_cmd  
                _,
                '-hide_banner', '-loglevel', 'info',
                '-re',
                '-f', 'mjpeg',
                '-reconnect', '', '-reconnect_streamed', '', '-reconnect_delay_ma', '',
                '-thread_queue_size', '',
                '-framerate', target_fps,  # (-  option d'entràÂ©e)
                '-i', recording.camera_url,
                '-fflags', '+genpts',
                '-use_wallclock_as_timestamps', '',
                # ortie sans forcer vsync/r de nouveau laisser ffmpeg utiliser le framerate d'entràÂ©e
                '-cv', 'lib',
                '-preset', self.video_quality'preset'],
                '-tune', 'zerolatency',
                '-pi_fmt', 'yuvp',
                '-profilev', 'main',
                '-movflags', '+faststart',
                '-crf', '',
                '-g', str(int(target_fps) * ),
                '-an',
                recording.output_path
            ]
            logger.info(f"à°ÂÂÂ¬ (ingle) mpeg  cmd {' '.join(ffmpeg_cmd)}")
            process  self._spawn_ffmpeg_process(ffmpeg_cmd, recording.session_id)
            if process.poll() is not one
                raise untimerror('mpeg non dàÂ©marràÂ©')
            self.recording_processesrecording.session_id]  process
            recording.status  'recording'
            recording.process  process
            recording.recording_type  'mjpeg_single'
            recording.start_time  datetime.now()
            threading.imer(self.ma_recording_duration, lambda self._auto_timeout_stop(recording.session_id)).start()
            return rue
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur dàÂ©marrage  single {e}")
            recording.status  'error'
            recording.error  str(e)
            return alse
    def _start_ffmpeg_recording(self, recording ecordingask) - bool
        """àÂ©marre un enregistrement avec mpeg ()."""
        try
            ffmpeg_cmd  
                _,
                '-rtsp_transport', 'tcp',
                '-i', recording.camera_url,
                '-cv', 'lib',
                '-preset', self.video_quality'preset'],
                '-tune', self.video_quality'tune'],
                '-crf', '',
                '-ca', 'aac', '-ba', 'k',
                '-movflags', '+faststart',
                recording.output_path
            ]
            logger.info(f"à°ÂÂÂ¬ àÂ©marrage mpeg  {recording.session_id}")
            process  self._spawn_ffmpeg_process(ffmpeg_cmd, recording.session_id)
            if process.poll() is not one
                raise untimerror("mpeg n'a pas pu dàÂ©marrer")
            self.recording_processesrecording.session_id]  process        
            recording.status  'recording'
            recording.process  process
            recording.recording_type  'rtsp'
            recording.start_time  datetime.now()
            threading.imer(
                self.ma_recording_duration,
                lambda self._auto_timeout_stop(recording.session_id)
            ).start()
            return rue
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur lors du dàÂ©marrage de mpeg {e}")
            recording.status  'error'
            recording.error  str(e)
            return alse
    
    def _start_opencv_recording(self, recording ecordingask) - bool
        """àÂ©marre un enregistrement avec pen"""
        try
            # ràÂ©er un stream camàÂ©ra
            camera  ameratream(recording.camera_url)
            
            # ssayer de dàÂ©marrer et récupérer un frame
            start_success  camera.start()
            frame_success  alse
            resolution  one
            
            if start_success
                # ttendre un peu pour avoir des frames
                time.sleep()
                
                # ssayer de récupérer un frame
                success, frame  camera.get_frame()
                frame_success  success
                
                if success and frame is not one
                    height, width  frame.shape]
                    resolution  {"width" width, "height" height}
            
            if not start_success
                raise untimerror(f"mpossible de dàÂ©marrer la capture pour {recording.camera_url}")
            
            # nregistrer le stream
            recording.camera_stream  camera
            recording.status  'recording'
            recording.recording_type  'opencv'
            recording.start_time  datetime.now()
            
            # ancer le thread d'enregistrement pen
            record_thread  threading.hread(
                targetself._opencv_recording_thread,
                args(recording.session_id, recording),
                daemonrue
            )
            record_thread.start()
            
            # imer auto-stop sàÂ©curitàÂ©
            threading.imer(
                self.ma_recording_duration,
                lambda self._auto_timeout_stop(recording.session_id)
            ).start()
            
            return rue
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur lors du dàÂ©marrage d'pen {e}")
            recording.status  'error'
            recording.error  str(e)
            return alse
    
    def _opencv_recording_thread(self, session_id str, recording ecordingask)
        """hread d'enregistrement vidàÂ©o avec pen"""
        try
            camera  self.camera_streams.get(session_id)    
            if not camera
                raise untimerror(f"tream camàÂ©ra non trouvé pour {session_id}")
            
            # àÂ©cupàÂ©rer un premier frame pour obtenir les dimensions    
            success, frame  camera.get_frame()
            if not success or frame is one
                raise untimerror("mpossible d'obtenir le premier frame")
            
            height, width  frame.shape]
            fps  self.video_quality'fps']
            
            # onfiguration de l'encodeur
            fourcc  cv.ideoriter_fourcc(*'mpv')
            out  cv.ideoriter(recording.output_path, fourcc, fps, (width, height))
            
            start_time  time.time()
            frame_count  
            last_frame_time  start_time
            
            while rue
                # àÂ©rifier si on doit s'arràÂªter
                with self.lock
                    if session_id not in self.recordings or self.recordingssession_id].status  'stopping'
                        break
                
                # àÂ©cupàÂ©rer un frame
                success, frame  camera.get_frame()
                if not success or frame is one
                    time.sleep(.)  # ause courte pour àÂ©viter  %
                    continue
                
                # àÂcrire le frame
                out.write(frame)
                frame_count + 
                
                # especter le  cible
                current_time  time.time()
                target_time  last_frame_time + (. / fps)
                if current_time  target_time
                    time.sleep(target_time - current_time)
                
                last_frame_time  time.time()
            
            # ettoyer les ressources
            out.release()
            logger.info(f"✅"
 nregistrement pen terminàÂ© {session_id}, {frame_count} frames")
            
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur dans le thread pen pour {session_id} {e}")
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur dans le thread pen pour {session_id} {e}")
            with self.lock
                if session_id in self.recordings
                    self.recordingssession_id].status  'error'
                    self.recordingssession_id].error  str(e)
    
    def _auto_timeout_stop(self, session_id str)
        with self.lock
            if session_id in self.recordings and 
               self.recordingssession_id].status  'recording'
                logger.warning(f"à¢ÂÂ±à¯Â¸Â uto-stop (duràÂ©e ma atteinte) session {session_id}")
                try
                    self.stop_recording(session_id)
                ecept ception as e
                    logger.error(f"rreur auto-stop {e}")

    def _finalize_recording(self, session_id str) - ictstr, ny]
        """inalise l'enregistrement et cràÂ©e l'entràÂ©e en base (tolàÂ©rant si ffprobe absent)."""
        try
            recording  self.recordingssession_id]
            if not os.path.eists(recording.output_path)
                return {'status''error','error'f"ichier vidàÂ©o non trouvé {recording.output_path}", 'message''inalisation impossible'}
            duration_seconds  one
            nb_frames  one
            probe_ok  alse
            try
                probe_cmd  
                    _,
                    '-v','error',
                    '-select_streams','v',
                    '-show_entries','streamduration,nb_frames',
                    '-of','defaultnoprint_wrappers',
                    recording.output_path
                ]
                probe  subprocess.run(probe_cmd, stdoutsubprocess., stderrsubprocess., universal_newlinesrue, timeout)
                probe_ok  probe.returncode  
                if probe_ok
                    for line in probe.stdout.splitlines()
                        if line.startswith('duration')
                            try duration_seconds  float(line.split('')])
                            ecept pass
                        elif line.startswith('nb_frames')
                            try nb_frames  int(line.split('')])
                            ecept pass
                else
                    if 'moov atom not found' in probe.stderr.lower()
                        logger.error(f"à¢ÂÂ moov absent {session_id}")
            ecept ileotoundrror
                logger.warning("ffprobe introuvable - fallback estimation duràÂ©e")
            ecept ception as pe
                logger.warning(f"robe àÂ©chec {pe}")
            file_size  self._get_file_size(recording.output_path)
            wallclock_secs  (datetime.now()-recording.start_time).total_seconds()
            if duration_seconds is one
                duration_seconds  ma(, int(wallclock_secs))
            target_fps  self.video_quality.get('fps',)
            est_from_frames  (nb_frames/target_fps) if (nb_frames and target_fps) else one
            if est_from_frames and abs(est_from_frames - wallclock_secs)  
                logger.warning(
                    f"à¢ÂÂ±à¯Â¸Â cart duràÂ©e wallclock{wallclock_secs.f}s ffprobe{duration_seconds.f}s frames_est{est_from_frames.f}s nb_frames{nb_frames}")
            # àÂtirement si ratio important (.) et frames_est proche duràÂ©e actuelle (indiquant timestamps compressàÂ©s)
            stretched  alse
            backup_path  one
            if wallclock_secs   and duration_seconds   and wallclock_secs/duration_seconds  .
                ratio  wallclock_secs / duration_seconds
                ok, new_dur, backup_path  self._stretch_video_duration(recording.output_path, ratio)
                if ok and new_dur  duration_seconds
                    duration_seconds  new_dur
                    stretched  rue
            # eprobe apràÂ¨s àÂ©ventuel stretch (duràÂ©e plus pràÂ©cise)
            if stretched
                try
                    probe  subprocess.run(
                        _,'-v','error','-select_streams','v','-show_entries','streamduration','-of','defaultnoprint_wrappers',recording.output_path
                    ],stdoutsubprocess.,stderrsubprocess.,universal_newlinesrue,timeout)
                    if probe.returncode
                        for line in probe.stdout.splitlines()
                            if line.startswith('duration')
                                try duration_secondsfloat(line.split('')])
                                ecept pass
                ecept ception
                    pass
            # ejet si fichier tràÂ¨s court avant cràÂ©ation 
            if duration_seconds   or file_size  *
                return {'status''error','error''ichier incomplet','file_size'file_size,'duration'duration_seconds,'nb_frames'nb_frames}
            thumb  self._generate_thumbnail(recording.output_path, recording.session_id)
            video  ideo(
                titlerecording.session_name,
                file_urlf"/videos/{os.path.basename(recording.output_path)}",
                thumbnail_urlf"/thumbnails/{recording.session_id}.jpg" if thumb else one,
                durationint(duration_seconds),
                file_sizefile_size,
                court_idrecording.court_id,
                user_idrecording.user_id,
                recorded_atrecording.start_time,
                is_unlockedalse,
                credits_cost,
            )
            db.session.add(video) db.session.commit()
            logger.info(
                f"✅"
 idàÂ©o validàÂ©e {video.id} dur{duration_seconds.f}s wallclock{wallclock_secs.f}s nb_frames{nb_frames} taille{file_size} stretched{stretched}")
            return {
                'status''completed',
                'video_id'video.id,
                'video_filename'os.path.basename(recording.output_path),
                'duration'int(duration_seconds),
                'wallclock_duration'int(wallclock_secs),
                'nb_frames'nb_frames,
                'file_size'file_size,
                'thumbnail_url'video.thumbnail_url,
                'stretched' stretched,
                'original_backup' backup_path if stretched else one
            }
        ecept ception as e
            logger.error(f"à¢ÂÂ inalisation erreur {e}")
            return {'status''error','error'str(e)}
    
    def test_camera_connection(self, camera_url str) - ictstr, ny]
        """
        este la conneion àÂ  une camàÂ©ra.
        
        rgs
            camera_url  de la camàÂ©ra àÂ  tester
            
        eturns
            àÂ©sultat du test
        """
        try
            logger.info(f"à°ÂÂÂ est de conneion àÂ  la camàÂ©ra {camera_url}")
            
            # ràÂ©er un stream de camàÂ©ra temporaire
            camera  ameratream(camera_url)
            
            # ssayer de dàÂ©marrer et récupérer un frame
            start_success  camera.start()
            frame_success  alse
            resolution  one
            
            if start_success
                # ttendre un peu pour avoir des frames
                time.sleep()
                
                # ssayer de récupérer un frame
                success, frame  camera.get_frame()
                if success and frame is not one
                    height, width  frame.shape]
                    resolution  {"width" width, "height" height}
            
            # rràÂªter proprement
            camera.stop()
            
            return {
                'status' 'success' if start_success and frame_success else 'error',
                'connection' start_success,
                'frames_available' frame_success,
                'resolution' resolution,
                'error' camera.last_error,
                'url' camera_url
            }
            
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur lors du test de la camàÂ©ra {e}")
            return {
                'status' 'error',
                'connection' alse,
                'frames_available' alse,
                'error' str(e),
                'url' camera_url
            }
    
    # ------ àÂ©thodes privàÂ©es ------
    
    def _validate_court(self, court_id int) - ourt
        """alide et ràÂ©cupàÂ¨re un terrain"""
        court  ourt.query.get(court_id)
        if not court
            raise aluerror(f"errain {court_id} non trouvé")
        return court
    
    def _validate_user(self, user_id int) - ser
        """alide et ràÂ©cupàÂ¨re un utilisateur"""
        user  ser.query.get(user_id)
        if not user
            raise aluerror(f"tilisateur {user_id} non trouvé")
        return user
    
    def _get_camera_url(self, court ourt) - str
        """àÂ©cupàÂ¨re l' de la camàÂ©ra pour un terrain"""
        if hasattr(court, 'camera_url') and court.camera_url
            return court.camera_url
        else
            #  de simulation pour les tests
            return f"http//localhost/api/courts/{court.id}/camera_stream"
    
    def _is_rtsp_url(self, url str) - bool
        """àÂ©termine si l' est un flu """
        return url.lower().startswith(('rtsp//', 'rtsps//'))
    
    def _is_mjpeg_url(self, url str) - bool
        """àÂ©termine si l' est un flu """
        url_lower  url.lower()
        return (url_lower.endswith(('.mjpg', '.mjpeg', '.cgi')) or 
                'mjpg' in url_lower or 'mjpeg' in url_lower)
    
    def _start_mjpeg_recording_segmented(self, recording ecordingask) - bool
        """ncien mode segmentàÂ© utilise ecordinganager (upload par segments)."""
        try
            result  self.mjpeg_manager.start_recording(
                recording_idrecording.session_id,
                mjpeg_urlrecording.camera_url,
                session_namerecording.session_name,
                segment_duration  # configurable via futur env si besoin
            )
            recording.recording_type  'mjpeg_bunny'
            recording.bunny_session_id  result'session_id']
            recording.status  'recording'
            recording.start_time  datetime.now()
            logger.info(f"à°ÂÂÂ¬ (egmented) nregistrement  dàÂ©marràÂ© vers unny {recording.session_id}")
            return rue
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur dàÂ©marrage  segmentàÂ© {e}")
            recording.status  'error'
            recording.error  str(e)
            return alse

    def _spawn_ffmpeg_process(self, cmd list, session_id str)
        """ance mpeg avec stdin  pour pouvoir envoyer 'q' et lit stderr en arriàÂ¨re-plan.
        mpàÂªche le blocage des pipes (memory leak) et permet un arràÂªt propre àÂ©crivant l'atome moov."""
        process  subprocess.open(
            cmd,
            stdinsubprocess.,
            stdoutsubprocess.,
            stderrsubprocess.,
            universal_newlinesrue,
            bufsize
        )
        # hread lecteur stderr (àÂ©vite remplissage buffer)
        def _drain()
            try
                for line in process.stderr
                    if not line
                        break
                    if 'frame' in line or 'fps' in line
                        continue  # trop verbeu
                    logger.debug(f"mpeg{session_id}] {line.strip()}")
            ecept ception
                pass
        t  threading.hread(target_drain, daemonrue)
        t.start()
        return process

    def _graceful_stop_ffmpeg(self, process subprocess.open, session_id str)
        """ente un arràÂªt dou (envoie 'q') pour que mpeg àÂ©crive la fin du conteneur ."""
        if process.poll() is not one
            return
        try
            if process.stdin
                try
                    process.stdin.write('q')
                    process.stdin.flush()
                ecept ception
                    pass
            # ttendre àÂ©criture trailer
            process.wait(timeout)
        ecept subprocess.imeoutpired
            try
                process.terminate()  # indows erminaterocess
                process.wait(timeout)
            ecept ception
                try
                    process.kill()
                ecept ception
                    pass

    def _start_mjpeg_recording_single(self, recording ecordingask) - bool
        """àÂ©marre un enregistrement  (mode single) avec cadence temps ràÂ©el corrigàÂ©e.
        justements
          - àÂ©placer le framerate en option 'àÂ (-framerate) avant -i pour que mpeg gàÂ©nàÂ¨re des timestamps espacàÂ©s
          - etirer combo '-vsync cfr -r fps' en sortie qui compressait le temps lorsque les frames arrivaient en rafale
          - onserver -re pour limiter la lecture si applicable
        """
        try
            target_fps  str(self.video_quality.get('fps', ))
            ffmpeg_cmd  
                _,
                '-hide_banner', '-loglevel', 'info',
                '-re',
                '-f', 'mjpeg',
                '-reconnect', '', '-reconnect_streamed', '', '-reconnect_delay_ma', '',
                '-thread_queue_size', '',
                '-framerate', target_fps,  # (-  option d'entràÂ©e)
                '-i', recording.camera_url,
                '-fflags', '+genpts',
                '-use_wallclock_as_timestamps', '',
                # ortie sans forcer vsync/r de nouveau laisser ffmpeg utiliser le framerate d'entràÂ©e
                '-cv', 'lib',
                '-preset', self.video_quality'preset'],
                '-tune', 'zerolatency',
                '-pi_fmt', 'yuvp',
                '-profilev', 'main',
                '-movflags', '+faststart',
                '-crf', '',
                '-g', str(int(target_fps) * ),
                '-an',
                recording.output_path
            ]
            logger.info(f"à°ÂÂÂ¬ (ingle) mpeg  cmd {' '.join(ffmpeg_cmd)}")
            process  self._spawn_ffmpeg_process(ffmpeg_cmd, recording.session_id)
            if process.poll() is not one
                raise untimerror('mpeg non dàÂ©marràÂ©')
            self.recording_processesrecording.session_id]  process
            recording.status  'recording'
            recording.process  process
            recording.recording_type  'mjpeg_single'
            recording.start_time  datetime.now()
            threading.imer(self.ma_recording_duration, lambda self._auto_timeout_stop(recording.session_id)).start()
            return rue
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur dàÂ©marrage  single {e}")
            recording.status  'error'
            recording.error  str(e)
            return alse
    def _start_ffmpeg_recording(self, recording ecordingask) - bool
        """àÂ©marre un enregistrement avec mpeg ()."""
        try
            ffmpeg_cmd  
                _,
                '-rtsp_transport', 'tcp',
                '-i', recording.camera_url,
                '-cv', 'lib',
                '-preset', self.video_quality'preset'],
                '-tune', self.video_quality'tune'],
                '-crf', '',
                '-ca', 'aac', '-ba', 'k',
                '-movflags', '+faststart',
                recording.output_path
            ]
            logger.info(f"à°ÂÂÂ¬ àÂ©marrage mpeg  {recording.session_id}")
            process  self._spawn_ffmpeg_process(ffmpeg_cmd, recording.session_id)
            if process.poll() is not one
                raise untimerror("mpeg n'a pas pu dàÂ©marrer")
            self.recording_processesrecording.session_id]  process        
            recording.status  'recording'
            recording.process  process
            recording.recording_type  'rtsp'
            recording.start_time  datetime.now()
            threading.imer(
                self.ma_recording_duration,
                lambda self._auto_timeout_stop(recording.session_id)
            ).start()
            return rue
        ecept ception as e
            logger.error(f"à¢ÂÂ rreur lors du dàÂ©marrage de mpeg {e}")
            recording.status  'error'
            recording.error  str(e)
            return alse
    
    def _start_opencv_recording(self, recording ecordingask) - bool
        """àÂ©marre un enregistrement avec pen"""
        try
            # ràÂ©er un stream camàÂ©ra
            camera  ameratream(recording.camera_url)
            
            # ssayer de dàÂ©marrer et récupérer un frame
            start_success  camera.start()
            frame_success  alse
            resolution  one
            
            if start_success
                # ttendre un peu pour avoir des frames
                time.sleep()
                
                # ssayer de récupérer un frame
                success, frame  camera.get_frame()
                frame_success  success
                
                if success and frame is not one
                    height, width  frame.shape]
                    resolution  {

width width, height height}
            
            # rràªter proprement
            camera.stop()
            
            return {
                'status' 'success' if start_success and frame_success else 'error',
                'connection' start_success,
                'frames_available' frame_success,
                'resolution' resolution,
                'error' camera.last_error if hasattr(camera, 'last_error') else one,
                'url' camera_url
            }
            
        ecept ception as e
            logger.error(f'

rreur

lors

du

test

de

la

caméra

e

)
            return {
                'status' 'error',
                'connection' alse,
                'frames_available' alse,
                'error' str(e),
                'url' camera_url
            }