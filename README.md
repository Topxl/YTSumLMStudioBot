# YouTube Bot Telegram

Un bot Telegram intelligent qui résume les vidéos YouTube et répond à vos questions sur leur contenu.

## Fonctionnalités

- 📝 Résumé automatique des vidéos YouTube
- 🎙️ Conversion des résumés en audio
- ❓ Réponses aux questions sur le contenu des vidéos
- 🔄 Support multilingue (traduction automatique des sous-titres)
- 🎯 Mode de chat interactif
- 📊 Historique des conversations
- 🔔 Notifications pour les nouvelles vidéos des chaînes suivies

## Prérequis

- Python 3.8+
- Docker et Docker Compose
- Un token Telegram Bot (obtenu via [@BotFather](https://t.me/botfather))
- Une instance LM Studio en cours d'exécution

## Installation

1. Clonez le dépôt :
```bash
git clone https://github.com/Topxl/YTSumLMStudioBot
cd youtube_bot
```

2. Créez un fichier `.env` basé sur `.env.example` :
```bash
cp .env.example .env
```

3. Configurez les variables d'environnement dans le fichier `.env`

4. Lancez le bot avec Docker :
```bash
docker-compose up --build
```

## Configuration

Le bot nécessite les variables d'environnement suivantes dans le fichier `.env` :

- `TELEGRAM_BOT_TOKEN` : Token de votre bot Telegram
- `LM_API_URL` : URL de votre instance LM Studio
- `LM_MODEL_NAME` : Nom du modèle à utiliser

## Utilisation

### Commandes disponibles

- `/start` - Démarrer le bot
- `/help` - Afficher l'aide
- `/chat` - Activer le mode chat
- `/chat_mode` - Changer le mode de chat
- `/reset` - Réinitialiser l'historique de conversation
- `/subscribe` - S'abonner à une chaîne YouTube
- `/unsubscribe` - Se désabonner d'une chaîne
- `/list_subscriptions` - Afficher les abonnements
- `/question` - Poser une question sur une vidéo

### Exemples d'utilisation

1. **Résumé de vidéo** :
   Envoyez simplement le lien d'une vidéo YouTube au bot.

2. **Question sur une vidéo** :
   ```
   /question https://youtube.com/watch?v=VIDEO_ID ? Quelle est la conclusion principale ?
   ```

3. **Mode chat** :
   ```
   /chat
   Bonjour, peux-tu me résumer cette vidéo ?
   ```

## Structure du projet

```
youtube_bot/
├── bot.py              # Code principal du bot
├── requirements.txt    # Dépendances Python
├── docker-compose.yml  # Configuration Docker
├── .env.example       # Exemple de configuration
└── README.md          # Documentation
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