@echo off
TITLE Bot Telegram YouTube Summarizer

REM Vérification de Python
where python >nul 2>nul
IF %ERRORLEVEL% NEQ 0 (
    echo X Python n'est pas installe ou n'est pas dans le PATH.
    echo Veuillez installer Python depuis https://python.org/
    pause
    exit /b
)

REM Vérification du fichier .env
IF NOT EXIST .env (
    echo Fichier .env non trouve, creation a partir de .env.example...
    IF EXIST .env.example (
        copy .env.example .env
        echo Fichier .env cree avec succes.
        echo Veuillez editer ce fichier pour configurer vos variables d'environnement.
        echo N'oubliez pas de definir TELEGRAM_BOT_TOKEN, LM_API_URL et LM_MODEL_NAME.
        notepad .env
        pause
        exit /b
    ) ELSE (
        echo X Impossible de trouver .env.example. Veuillez creer un fichier .env manuellement.
        pause
        exit /b
    )
)

REM Installation des dépendances
echo Installation des dependances...
pip install -r requirements.txt

REM Lancement du bot
echo Lancement du bot Telegram...
python bot.py

pause 