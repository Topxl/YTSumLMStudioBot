# YouTube Bot Telegram

Un bot Telegram intelligent qui résume les vidéos YouTube et répond à vos questions sur leur contenu.

## Fonctionnalités

- 📝 Résumé automatique des vidéos YouTube
- 🎙️ Conversion des résumés en audio
- ❓ Réponses aux questions sur le contenu des vidéos
- 🔄 Support multilingue (traduction automatique des sous-titres)
- 🎯 Mode de chat interactif (libre ou guidé)
- 📊 Historique des conversations
- 🔔 Notifications pour les nouvelles vidéos des chaînes suivies

## Prérequis

- Python 3.8+
- Un token Telegram Bot (obtenu via [@BotFather](https://t.me/botfather))
- Une instance LM Studio en cours d'exécution

## Installation

1. Clonez le dépôt :
```bash
git clone https://github.com/Topxl/YTSumLMStudioBot
cd YTSumLMStudioBot
```

2. Créez un fichier `.env` basé sur `.env.example` :
```bash
cp .env.example .env
```

3. Configurez les variables d'environnement dans le fichier `.env`

## Lancement du bot

### Méthode 1 : Script de lancement (recommandé)

**Sur Linux/macOS :**
```bash
chmod +x run.sh  # Rendre le script exécutable (première fois uniquement)
./run.sh
```

**Sur Windows :**
```
Double-cliquez sur run.bat
```

### Méthode 2 : Lancement manuel

1. Installez les dépendances :
```bash
pip install -r requirements.txt
```

2. Lancez le bot :
```bash
python bot.py
```

### Méthode 3 : Avec Docker (optionnel)

```bash
docker-compose up --build
```

## Configuration

Le bot nécessite les variables d'environnement suivantes dans le fichier `.env` :

- `TELEGRAM_BOT_TOKEN` : Token de votre bot Telegram
- `LM_API_URL` : URL de votre instance LM Studio (ex: http://localhost:1234)

- `YOUTUBE_API_KEY` : (Optionnel) Clé API YouTube pour les abonnements



## Utilisation

### Commandes principales

| Commande longue | Raccourci | Description |
|----------------|-----------|-------------|
| `/start` | - | Démarrer le bot |
| `/help` | `/h` | Afficher l'aide |
| `/question` | `/q` | Poser une question sur une vidéo |
| `/chat` | `/c` | Activer le mode conversation |
| `/chat_mode` | `/mode` | Changer le mode de conversation |
| `/reset` | `/r` | Réinitialiser l'historique |
| `/subscribe` | `/sub` | S'abonner à une chaîne YouTube |
| `/unsubscribe` | `/unsub` | Se désabonner d'une chaîne |
| `/list_subscriptions` | `/list` ou `/subs` | Afficher les abonnements |

### Exemples d'utilisation

1. **Résumé de vidéo** :
   Envoyez simplement le lien d'une vidéo YouTube au bot.

2. **Question sur une vidéo** (nouvelle version simplifiée) :
   ```
   /q https://youtube.com/watch?v=VIDEO_ID Quelle est la conclusion principale ?
   ```

3. **Mode chat** :
   ```
   /c
   Bonjour, peux-tu me résumer cette vidéo ?
   ```

4. **Abonnement à une chaîne** :
   ```
   /sub https://www.youtube.com/@NomDeLaChaine
   ```

## Fonctionnement du bot

- **Résumé automatique** : Envoyez un lien YouTube et le bot récupère les sous-titres, les résume et convertit le résumé en audio.
- **Questions** : Posez des questions spécifiques sur le contenu d'une vidéo.
- **Mode chat** : Discutez avec le bot sur n'importe quel sujet, en incluant des liens YouTube si nécessaire.
- **Abonnements** : Recevez automatiquement des résumés des nouvelles vidéos de vos chaînes préférées.

## Structure du projet

```
youtube_bot/
├── bot.py              # Code principal du bot
├── requirements.txt    # Dépendances Python
├── run.sh              # Script de lancement pour Linux/macOS
├── run.bat             # Script de lancement pour Windows
├── subscriptions.json  # Stockage des abonnements
├── docker-compose.yml  # Configuration Docker (optionnel)
├── Dockerfile          # Configuration Docker (optionnel)
├── .env.example        # Exemple de configuration
└── README.md           # Documentation
```

## Contribution

Les contributions sont les bienvenues ! N'hésitez pas à :
1. Fork le projet
2. Créer une branche pour votre fonctionnalité
3. Commiter vos changements
4. Pousser vers la branche
5. Ouvrir une Pull Request

## Licence

Ce projet est sous licence MIT. Voir le fichier `LICENSE` pour plus de détails. 