# 🔐 Configuration de l'Authentification Google

Ce guide vous aide à configurer l'authentification Google ("Se connecter avec Google") pour Spovio.

## 1. Prérequis

Vous devez avoir accès à la console Google Cloud : [https://console.cloud.google.com/](https://console.cloud.google.com/)

## 2. Récupérer vos identifiants

1. Allez dans **APIs & Services** > **Credentials** (Identifiants).
2. Sélectionnez votre client OAuth 2.0 (ex: "Client Web 1").
3. Vous trouverez ici :
   - **ID client** : `293940451036-olo8rcnugtkuevfs3gk9de5rnslqd729.apps.googleusercontent.com`
   - **Code secret du client** : (C'est une chaîne de caractères secrète, ne la partagez pas !)

## 3. Configuration du fichier .env

Ouvrez le fichier `.env` à la racine du projet backend et assurez-vous que ces lignes sont présentes :

```env
GOOGLE_CLIENT_ID=293940451036-olo8rcnugtkuevfs3gk9de5rnslqd729.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=VOTRE_SECRET_ICI
GOOGLE_REDIRECT_URI=http://localhost:5000/api/auth/google/callback
```

> ⚠️ **IMPORTANT** : Remplacez `VOTRE_SECRET_ICI` par le vrai code secret copié depuis la console Google.

## 4. Configuration des URIs de redirection (Console Google)

Dans la configuration de votre client OAuth sur la console Google, assurez-vous d'avoir ajouté :

### Origines JavaScript autorisées
- `http://localhost:3000` (Votre frontend React)
- `http://localhost:5000` (Votre backend Flask - optionnel mais recommandé)

### URI de redirection autorisés
- `http://localhost:5000/api/auth/google/callback`

## 5. Validation

1. Redémarrez votre serveur backend Python :
   ```powershell
   python app.py
   ```
2. Vous ne devriez plus voir le message d'avertissement "GOOGLE_CLIENT_ID n'est pas configuré".
3. Essayez de vous connecter via le frontend.
