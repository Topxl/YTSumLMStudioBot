#!/bin/bash

# Vérification de Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 n'est pas installé. Veuillez l'installer avant de continuer."
    exit 1
fi

# Vérification de pip
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip3 n'est pas installé. Veuillez l'installer avant de continuer."
    exit 1
fi

# Vérification de .env
if [ ! -f .env ]; then
    echo "⚠️ Fichier .env non trouvé, création à partir de .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ .env créé. Veuillez éditer ce fichier pour configurer vos variables d'environnement."
        echo "   N'oubliez pas de définir TELEGRAM_BOT_TOKEN et LM_API_URL."
        exit 1
    else
        echo "❌ Impossible de trouver .env.example. Veuillez créer un fichier .env manuellement."
        exit 1
    fi
fi

# Installation des dépendances
echo "📦 Installation des dépendances..."
pip3 install -r requirements.txt

# Lancement du bot
echo "🚀 Lancement du bot Telegram..."
python3 bot.py 