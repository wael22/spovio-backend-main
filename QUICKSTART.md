# ⚡ PadelVar - Quickstart Vidéo

## 🚀 Démarrage Rapide (5 minutes)

### 1. Installation

```bash
cd padelvar-backend-main

# Installer dépendances
pip install flask requests pillow opencv-python-headless

# Vérifier FFmpeg
ffmpeg -version
```

### 2. Démarrer Backend

```bash
python -m flask run
```

### 3. Tester

```bash
# Santé système
curl http://localhost:5000/api/video/health
```

**Résultat attendu :**
```json
{
  "status": "healthy",
  "ffmpeg_available": true,
  "active_sessions": 0,
  "pipeline": "Camera → video_proxy_server.py → FFmpeg → MP4"
}
```

---

## 📡 Test Complet (avec auth)

### 1. Se Connecter

```bash
# Se connecter (obtenir token)
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@mysmash.com", "password": "votre_mot_de_passe"}'

# Copier le token
export TOKEN="eyJ0eXAiOiJKV1QiLCJhbGc..."
```

### 2. Créer Session

```bash
curl -X POST http://localhost:5000/api/video/session/create \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"terrain_id": 1}'

# Copier le session_id
export SESSION_ID="sess_1_1701234567"
```

### 3. Démarrer Enregistrement

```bash
curl -X POST http://localhost:5000/api/video/record/start \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"session_id\": \"$SESSION_ID\", \"duration_minutes\": 5}"
```

### 4. Voir Preview

```bash
# Ouvrir dans navigateur
open "http://localhost:5000/api/preview/$SESSION_ID/stream.mjpeg"

# Ou télécharger snapshot
curl "http://localhost:5000/api/preview/$SESSION_ID/snapshot.jpg" \
  -H "Authorization: Bearer $TOKEN" \
  --output snapshot.jpg
```

### 5. Vérifier Statut

```bash
curl "http://localhost:5000/api/video/record/status/$SESSION_ID" \
  -H "Authorization: Bearer $TOKEN"
```

### 6. Arrêter Enregistrement

```bash
curl -X POST http://localhost:5000/api/video/record/stop \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"session_id\": \"$SESSION_ID\"}"
```

### 7. Télécharger Vidéo

```bash
curl "http://localhost:5000/api/video/files/$SESSION_ID/download?club_id=1" \
  -H "Authorization: Bearer $TOKEN" \
  --output match.mp4
```

---

## 🎨 Frontend (React)

```typescript
// Installation
npm install axios

// Utilisation
import { createSession, startRecording, stopRecording } from './videoApi';

// Workflow
const session = await createSession(terrainId);
await startRecording(session.session_id, 90);

// Preview
<img src={`/api/preview/${session.session_id}/stream.mjpeg`} />

// Stop
const videoPath = await stopRecording(session.session_id);
```

**Voir exemples complets** : `FRONTEND_INTEGRATION.md`

---

## 🔧 Configuration Caméra

### MJPEG

```python
# Dans la base de données (table Court)
camera_url = "http://192.168.1.100/mjpeg"
```

### RTSP

```python
camera_url = "rtsp://admin:password@192.168.1.100:554/stream"
```

### HTTP Générique

```python
camera_url = "http://192.168.1.100:8080/video"
```

---

## 📊 Monitoring

```bash
# Sessions actives
curl http://localhost:5000/api/video/session/list \
  -H "Authorization: Bearer $TOKEN"

# Enregistrements en cours
curl http://localhost:5000/api/video/health

# Vidéos disponibles
curl "http://localhost:5000/api/video/files/list?club_id=1" \
  -H "Authorization: Bearer $TOKEN"

# Nettoyer sessions orphelines
curl -X POST http://localhost:5000/api/video/cleanup \
  -H "Authorization: Bearer $TOKEN"
```

---

## 🐛 Dépannage Rapide

### Problème : FFmpeg non trouvé

```bash
# Installer FFmpeg
sudo apt install ffmpeg  # Ubuntu/Debian
brew install ffmpeg      # macOS
```

### Problème : Port déjà utilisé

```bash
# Vérifier ports
netstat -tuln | grep 8080

# Libérer port
sudo kill $(lsof -ti:8080)
```

### Problème : Caméra inaccessible

```bash
# Tester connexion MJPEG
curl -I http://192.168.1.100/mjpeg

# Tester connexion RTSP
ffprobe rtsp://admin:password@192.168.1.100:554/stream
```

### Problème : Vidéo vide

```bash
# Vérifier logs FFmpeg
cat logs/video/<session_id>.ffmpeg.log

# Vérifier permissions
ls -la static/videos/<club_id>/
```

---

## 📚 Documentation Complète

| Document | Description |
|----------|-------------|
| `QUICKSTART.md` | Ce guide (démarrage rapide) |
| `VIDEO_SYSTEM_README.md` | Documentation technique complète |
| `MIGRATION_VIDEO_SYSTEM.md` | Guide de migration |
| `FRONTEND_INTEGRATION.md` | Exemples frontend (React, Vue) |
| `CLEANUP_OLD_SYSTEM.md` | Nettoyage ancien système |
| `IMPLEMENTATION_SUMMARY.md` | Récapitulatif implémentation |

---

## ✅ Checklist Démarrage

- [ ] FFmpeg installé (`ffmpeg -version`)
- [ ] Dépendances Python installées (`pip install -r requirements_video.txt`)
- [ ] Backend démarre (`python -m flask run`)
- [ ] API health répond (`curl http://localhost:5000/api/video/health`)
- [ ] Token obtenu (connexion)
- [ ] Session créée
- [ ] Enregistrement démarré
- [ ] Preview visible
- [ ] Enregistrement arrêté
- [ ] Vidéo téléchargée

---

## 🎉 C'est Tout !

Le système vidéo PadelVar est **prêt à l'emploi**.

**Pipeline** : `Caméra → video_proxy_server.py → FFmpeg → MP4`

**Support** : Consultez les logs dans `logs/video/<session_id>.ffmpeg.log`
