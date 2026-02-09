# Configuration SMTP pour MySmash

## 📧 Configuration SMTP (Email de vérification)

Pour activer l'envoi d'emails de vérification, configurez votre serveur SMTP en ajoutant ces variables d'environnement.

### Option 1: Gmail (Recommandé pour le développement)

1. **Activer l'authentification à deux facteurs** sur votre compte Gmail

2. **Générer un mot de passe d'application**:
   - Allez sur https://myaccount.google.com/apppasswords
   - Sélectionnez "Mail" et "Other (Custom name)"
   - Nommez-le "MySmash Backend"
   - Copiez le mot de passe généré (16 caractères)

3. **Créer un fichier `.env`** à la racine du projet backend:

```bash
# SMTP Configuration (Gmail)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=mysmashpadel@gmail.com
SMTP_PASSWORD=fssecphvikhkkbds
SMTP_FROM_EMAIL=mysmashpadel@gmail.com

# Frontend URL
FRONTEND_URL=http://localhost:5173

# Durée de validité du code (en heures)
VERIFICATION_CODE_EXPIRY_HOURS=24
```

### Option 2: SendGrid (Production recommandée)

```bash
# SMTP Configuration (SendGrid)
SMTP_SERVER=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USERNAME=apikey
SMTP_PASSWORD=votre_api_key_sendgrid
SMTP_FROM_EMAIL=noreply@votredomaine.com
FRONTEND_URL=https://votredomaine.com
```

### Option 3: Mailgun

```bash
# SMTP Configuration (Mailgun)
SMTP_SERVER=smtp.mailgun.org
SMTP_PORT=587
SMTP_USERNAME=postmaster@votredomaine.mailgun.org
SMTP_PASSWORD=votre_password_mailgun
SMTP_FROM_EMAIL=noreply@votredomaine.com
FRONTEND_URL=https://votredomaine.com
```

## 🔧 Installation

1. **Créez le fichier `.env`** dans `padelvar-backend-main/`:

```powershell
# Depuis le dossier backend
cd C:\Users\PC\Desktop\e171abab-6030-4c66-be1d-b73969cd489a-files\padelvar-backend-main
New-Item -Path ".env" -ItemType File -Force
```

2. **Éditez `.env`** et ajoutez vos identifiants SMTP

3. **Redémarrez le serveur Flask**:

```powershell
# Arrêter le serveur actuel (Ctrl+C dans le terminal)
# Puis relancer:
python .\app.py
```

## ✅ Vérification

Après redémarrage, lors d'une nouvelle inscription:
- ✅ Si SMTP configuré: Email envoyé + log `✅ Email de vérification envoyé`
- ⚠️ Si SMTP non configuré: Code affiché dans les logs uniquement

## 🎯 Mode Développement (Sans SMTP)

En développement, si SMTP n'est pas configuré:
- Le code de vérification s'affiche dans les logs du serveur
- Cherchez: `🔑 CODE DE VÉRIFICATION (DEV ONLY): 123456`
- Utilisez ce code pour vérifier l'email

## 📝 Notes

- **Gmail**: Limite de 500 emails/jour (suffisant pour dev)
- **SendGrid**: 100 emails/jour gratuits (meilleur pour production)
- **Sécurité**: Ne committez JAMAIS le fichier `.env` (déjà dans `.gitignore`)
