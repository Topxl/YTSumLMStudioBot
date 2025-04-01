import os
import re
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled
from gtts import gTTS
import json
import urllib.parse
from datetime import datetime
from googleapiclient.discovery import build

# --- Config ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LM_API_URL = os.getenv("LM_API_URL")
LM_MODEL_NAME = os.getenv("LM_MODEL_NAME")

print("=== Configuration chargée ===")
print(f"TELEGRAM_TOKEN: {TELEGRAM_TOKEN[:10]}..." if TELEGRAM_TOKEN else "TELEGRAM_TOKEN non défini")
print(f"LM_API_URL: {LM_API_URL}" if LM_API_URL else "LM_API_URL non défini")
print(f"LM_MODEL_NAME: {LM_MODEL_NAME}" if LM_MODEL_NAME else "LM_MODEL_NAME non défini")
print("============================")

# --- Variables globales ---
CONVERSATION_HISTORY = {}  # Stocke l'historique des conversations par utilisateur
CHAT_ACTIVE = {}  # Indique si le mode chat est actif pour chaque utilisateur
CHAT_MODES = {
    "libre": "Mode libre (discussion ouverte)",
    "guidé": "Mode guidé (questions sur la vidéo)"
}
USER_CHAT_MODES = {}  # Mode de chat par utilisateur

# Structures pour les abonnements aux chaînes
CHANNEL_SUBSCRIPTIONS = {}  # Format: {user_id: {channel_id: channel_name}}
LATEST_VIDEOS = {}  # Format: {channel_id: [video_ids]}
SUBSCRIPTION_FILE = "subscriptions.json"
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "1800"))  # 30 minutes par défaut

# --- Utilitaires ---

def extract_video_id(url):
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11})",
        r"youtu\.be\/([0-9A-Za-z_-]{11})"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_subtitles(video_url):
    try:
        video_id = extract_video_id(video_url)
        if not video_id:
            return None, "[Erreur] Lien invalide ou ID introuvable."

        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        for transcript in transcript_list:
            if transcript.language_code == "fr":
                entries = transcript.fetch()
                return " ".join([entry.text for entry in entries]), None

        for transcript in transcript_list:
            if transcript.is_translatable:
                translated = transcript.translate('fr')
                entries = translated.fetch()
                return " ".join([entry.text for entry in entries]), None

        return None, "[Erreur] Aucun sous-titre utilisable ou traduisible trouvé."

    except TranscriptsDisabled:
        return None, "[Erreur] Les sous-titres sont désactivés pour cette vidéo."
    except Exception as e:
        return None, f"[Erreur récupération sous-titres] {str(e)}"

def split_text(text, max_chars=12000):
    parts = []
    while len(text) > max_chars:
        split_index = text[:max_chars].rfind(". ") + 1
        if split_index == 0:
            split_index = max_chars
        parts.append(text[:split_index].strip())
        text = text[split_index:].strip()
    parts.append(text.strip())
    return parts

def chat_with_lmstudio(messages):
    try:
        # Vérifier si les variables d'environnement sont définies
        if not LM_API_URL:
            return "[Erreur] Variable d'environnement LM_API_URL non définie dans le fichier .env"
        
        if not LM_MODEL_NAME:
            return "[Erreur] Variable d'environnement LM_MODEL_NAME non définie dans le fichier .env"
        
        # S'assurer que l'URL se termine par /v1/chat/completions
        api_url = LM_API_URL.rstrip('/')
        if not api_url.endswith('/v1/chat/completions'):
            api_url = f"{api_url}/v1/chat/completions"
        
        print(f"Envoi de requête à {api_url} avec le modèle {LM_MODEL_NAME}")
        
        # Préparer le prompt en combinant tous les messages
        prompt = ""
        for msg in messages:
            if msg["role"] == "system":
                prompt += f"System: {msg['content']}\n"
            elif msg["role"] == "user":
                prompt += f"Human: {msg['content']}\n"
            elif msg["role"] == "assistant":
                prompt += f"Assistant: {msg['content']}\n"
        
        # Format de requête pour LM Studio
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": float(os.getenv("LM_TEMPERATURE", "0.7")),
            "max_tokens": int(os.getenv("LM_MAX_TOKENS", "2000")),
            "stream": False
        }

        response = requests.post(api_url, json=payload)

        if response.status_code == 200:
            try:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    return result['choices'][0]['message']['content']
                else:
                    error_msg = "[Erreur LM Studio] Format de réponse invalide"
                    print(error_msg)
                    return error_msg
            except Exception as e:
                error_msg = f"[Erreur LM Studio] Erreur lors du parsing de la réponse: {str(e)}"
                print(error_msg)
                return error_msg
        else:
            error_msg = f"[Erreur LM Studio] Code {response.status_code} : {response.text}"
            print(error_msg)
            return error_msg
    except Exception as e:
        error_msg = f"[Erreur LM Studio] {str(e)}"
        print(error_msg)
        return error_msg

def summarize(text):
    chunks = split_text(text)
    summaries = []

    prompt = (
        "Fais un résumé du contenu en apportant un maximum de valeur au lecteur. "
        "Utilise des points clairs, sans répétition, et mets en avant les idées clés."
    )

    for chunk in chunks:
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": chunk}
        ]
        summary = chat_with_lmstudio(messages)
        summaries.append(summary)

    fusion_prompt = (
        "Voici plusieurs résumés partiels d'une vidéo. "
        "Fusionne-les en un résumé"
        "en mettant en avant les idées clés et les informations qui apportent le plus de valeur au lecteur."
    )

    messages = [
        {"role": "system", "content": fusion_prompt},
        {"role": "user", "content": "\n\n".join(summaries)}
    ]
    return chat_with_lmstudio(messages)

def ask_question_about_subtitles(subtitles, question):
    prompt = (
        f"Voici la transcription d'une vidéo YouTube :\n\n{subtitles}\n\n"
        f"Réponds à la question suivante de manière claire et utile : {question}"
    )
    messages = [
        {"role": "system", "content": "Tu es un assistant qui répond précisément à des questions sur une vidéo."},
        {"role": "user", "content": prompt}
    ]
    return chat_with_lmstudio(messages)

def text_to_audio(text, filename="resume.mp3"):
    tts = gTTS(text, lang='fr')
    tts.save(filename)
    return filename

# --- Gestion des abonnements ---

def save_subscriptions():
    """Sauvegarde les abonnements dans un fichier JSON."""
    with open(SUBSCRIPTION_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            "subscriptions": CHANNEL_SUBSCRIPTIONS,
            "latest_videos": LATEST_VIDEOS
        }, f, ensure_ascii=False, indent=2)
    print(f"Abonnements sauvegardés dans {SUBSCRIPTION_FILE}")

def load_subscriptions():
    """Charge les abonnements depuis un fichier JSON s'il existe."""
    global CHANNEL_SUBSCRIPTIONS, LATEST_VIDEOS
    if os.path.exists(SUBSCRIPTION_FILE):
        try:
            with open(SUBSCRIPTION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Convertir les clés user_id en entiers (car JSON les stocke comme strings)
                CHANNEL_SUBSCRIPTIONS = {int(user_id): channels for user_id, channels in data.get("subscriptions", {}).items()}
                LATEST_VIDEOS = data.get("latest_videos", {})
            print(f"Abonnements chargés depuis {SUBSCRIPTION_FILE}")
        except Exception as e:
            print(f"Erreur lors du chargement des abonnements: {e}")

def extract_channel_id(url):
    """Extrait l'ID de la chaîne à partir de l'URL."""
    # Nettoyer l'URL - supprimer les paramètres après ?
    if "?" in url:
        url = url.split("?")[0]
    
    if "youtube.com/channel/" in url:
        # Format: https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw
        return url.split("youtube.com/channel/")[1].split("/")[0]
    elif "youtube.com/c/" in url or "youtube.com/user/" in url:
        # Pour les URLs personnalisées, nous devrons faire une requête
        # à l'API YouTube pour obtenir l'ID de la chaîne
        return None
    elif "youtube.com/@" in url:
        # Format: https://www.youtube.com/@nomdelacha@ne
        return url.split("youtube.com/@")[1].split("/")[0]
    return None

def get_channel_info(url, api_key=None):
    """Obtient les informations de la chaîne à partir de l'URL."""
    try:
        # Nettoyer l'URL - supprimer les paramètres après ?
        if "?" in url:
            url = url.split("?")[0]
            
        # Essayer d'extraire directement l'ID de la chaîne
        channel_id = extract_channel_id(url)
        
        # Si nous avons l'ID direct de la chaîne
        if channel_id:
            # Si nous n'avons pas d'API key, nous pouvons juste renvoyer l'ID
            # et essayer d'extraire le nom depuis l'URL
            if not api_key:
                # Extraire le nom depuis l'URL pour @username
                if "youtube.com/@" in url:
                    channel_name = url.split("youtube.com/@")[1].split("/")[0]
                    return {"id": channel_id, "name": f"@{channel_name}"}
                return {"id": channel_id, "name": channel_id}

        # Si nous avons une API key, nous pouvons obtenir plus d'informations
        if api_key:
            youtube = build('youtube', 'v3', developerKey=api_key)
            
            # Si c'est une URL personnalisée, nous cherchons par le nom de la chaîne
            if not channel_id:
                # Extraire le nom personnalisé
                if "youtube.com/c/" in url:
                    custom_name = url.split("youtube.com/c/")[1].split("/")[0]
                elif "youtube.com/user/" in url:
                    custom_name = url.split("youtube.com/user/")[1].split("/")[0]
                elif "youtube.com/@" in url:
                    custom_name = url.split("youtube.com/@")[1].split("/")[0]
                else:
                    return None
                
                # Rechercher la chaîne par son nom
                search_response = youtube.search().list(
                    q=custom_name,
                    type='channel',
                    part='id,snippet',
                    maxResults=1
                ).execute()
                
                if search_response['items']:
                    item = search_response['items'][0]
                    return {
                        "id": item['id']['channelId'],
                        "name": item['snippet']['title']
                    }
                return None
            
            # Si nous avons déjà l'ID, nous obtenons directement les informations
            channel_response = youtube.channels().list(
                part='snippet',
                id=channel_id
            ).execute()
            
            if channel_response['items']:
                item = channel_response['items'][0]
                return {
                    "id": item['id'],
                    "name": item['snippet']['title']
                }
        
        # Si nous n'avons pas pu obtenir les informations complètes
        if channel_id:
            # Utiliser l'ID comme nom
            return {"id": channel_id, "name": channel_id}
        
        return None
    except Exception as e:
        print(f"Erreur lors de l'obtention des informations de la chaîne: {e}")
        # En cas d'erreur, si nous avons l'ID, nous le renvoyons
        if channel_id:
            return {"id": channel_id, "name": channel_id}
        return None

def get_latest_videos(channel_id, api_key=None, max_results=5):
    """Obtient les dernières vidéos d'une chaîne."""
    try:
        # Si nous n'avons pas d'API key, on ne peut pas récupérer les vidéos
        if not api_key:
            print(f"Aucune API key fournie pour récupérer les vidéos de {channel_id}")
            return []
        
        youtube = build('youtube', 'v3', developerKey=api_key)
        
        # Récupérer les dernières vidéos publiées
        search_response = youtube.search().list(
            channelId=channel_id,
            type="video",
            part="id,snippet",
            order="date",
            maxResults=max_results
        ).execute()
        
        videos = []
        for item in search_response.get("items", []):
            video_id = item["id"]["videoId"]
            video_title = item["snippet"]["title"]
            published_at = item["snippet"]["publishedAt"]
            videos.append({
                "id": video_id,
                "title": video_title,
                "published_at": published_at
            })
        
        return videos
    except Exception as e:
        print(f"Erreur lors de la récupération des vidéos pour {channel_id}: {e}")
        return []

async def check_new_videos(context):
    """Vérifie s'il y a de nouvelles vidéos sur les chaînes suivies."""
    try:
        print(f"Vérification des nouvelles vidéos ({datetime.now().strftime('%H:%M:%S')})")
        
        # Si nous n'avons pas de chaînes suivies, on arrête là
        if not CHANNEL_SUBSCRIPTIONS:
            print("Aucun abonnement trouvé.")
            return
        
        # Récupération de l'API key (optionnelle)
        api_key = os.getenv("YOUTUBE_API_KEY")
        
        # Pour chaque chaîne suivie
        for channel_id in set(sum([list(channels.keys()) for channels in CHANNEL_SUBSCRIPTIONS.values()], [])):
            # Si nous n'avons pas encore enregistré les dernières vidéos pour cette chaîne
            if channel_id not in LATEST_VIDEOS:
                LATEST_VIDEOS[channel_id] = []
            
            # Récupérer les dernières vidéos
            latest_videos = []
            
            # Si nous avons une API key, on peut utiliser l'API YouTube
            if api_key:
                latest_videos = get_latest_videos(channel_id, api_key)
            else:
                # Sinon, on utilise une approche basique (moins efficace)
                print(f"Pas d'API key pour YouTube, utilisation d'une méthode alternative pour {channel_id}")
                try:
                    # On pourrait utiliser une bibliothèque comme youtube-search-python ici
                    # Pour ce prototype, on considère que cette partie est traitée
                    pass
                except Exception as e:
                    print(f"Erreur lors de la récupération alternative: {e}")
            
            # Si nous n'avons pas réussi à récupérer les vidéos
            if not latest_videos:
                print(f"Aucune vidéo récupérée pour {channel_id}")
                continue
            
            # Filtre les nouvelles vidéos (non vues précédemment)
            known_video_ids = set(LATEST_VIDEOS[channel_id])
            new_videos = [video for video in latest_videos if video["id"] not in known_video_ids]
            
            # Si aucune nouvelle vidéo
            if not new_videos:
                print(f"Aucune nouvelle vidéo pour {channel_id}")
                continue
            
            print(f"Nouvelles vidéos pour {channel_id}: {len(new_videos)}")
            
            # Mettre à jour la liste des vidéos connues
            for video in new_videos:
                if video["id"] not in known_video_ids:
                    LATEST_VIDEOS[channel_id].append(video["id"])
            
            # Limiter la liste des vidéos connues (pour éviter qu'elle grossisse trop)
            LATEST_VIDEOS[channel_id] = LATEST_VIDEOS[channel_id][-50:]
            
            # Sauvegarder les abonnements
            save_subscriptions()
            
            # Traiter chaque nouvelle vidéo
            for video in new_videos:
                video_id = video["id"]
                video_title = video["title"]
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                
                # Récupérer les utilisateurs abonnés à cette chaîne
                subscribed_users = [
                    user_id for user_id, channels in CHANNEL_SUBSCRIPTIONS.items()
                    if channel_id in channels
                ]
                
                if not subscribed_users:
                    continue
                
                # Récupérer les sous-titres
                subtitles, error = get_subtitles(video_url)
                if error:
                    print(f"Erreur lors de la récupération des sous-titres: {error}")
                    continue
                
                # Résumer la vidéo
                summary = summarize(subtitles)
                
                # Créer le fichier audio
                audio_path = text_to_audio(summary, f"resume_{video_id}.mp3")
                
                # Pour chaque utilisateur abonné, envoyer le résumé
                for user_id in subscribed_users:
                    try:
                        channel_name = CHANNEL_SUBSCRIPTIONS[user_id][channel_id]
                        
                        # Envoi du message texte
                        message = (
                            f"🆕 *Nouvelle vidéo de {channel_name}*\n\n"
                            f"📺 [{video_title}]({video_url})\n\n"
                            f"📝 *Résumé* :\n{summary}"
                        )
                        
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=message,
                            parse_mode="Markdown"
                        )
                        
                        # Envoi du fichier audio
                        with open(audio_path, 'rb') as audio_file:
                            await context.bot.send_voice(
                                chat_id=user_id,
                                voice=audio_file,
                                caption=f"🎙️ Résumé audio de '{video_title}'"
                            )
                        
                        print(f"Résumé envoyé à l'utilisateur {user_id} pour la vidéo {video_id}")
                    except Exception as e:
                        print(f"Erreur lors de l'envoi du résumé à l'utilisateur {user_id}: {e}")
                
                # Supprimer le fichier audio après utilisation
                if os.path.exists(audio_path):
                    os.remove(audio_path)
        
        print("Vérification terminée.")
    except Exception as e:
        print(f"Erreur lors de la vérification des nouvelles vidéos: {e}")

def start_video_check_scheduler(app):
    """Démarre le planificateur pour vérifier périodiquement les nouvelles vidéos."""
    try:
        # Vérifier si le job_queue est disponible
        if hasattr(app, 'job_queue'):
            print(f"Configuration du planificateur pour vérifier les vidéos toutes les {CHECK_INTERVAL} secondes")
            app.job_queue.run_repeating(check_new_videos, interval=CHECK_INTERVAL, first=10)
            return True
        else:
            print("JobQueue non disponible. La vérification automatique des vidéos est désactivée.")
            return False
    except Exception as e:
        print(f"Erreur lors de la configuration du planificateur: {e}")
        return False

# --- Handlers Telegram ---

async def handle_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    CHAT_ACTIVE[user_id] = True
    USER_CHAT_MODES.setdefault(user_id, "libre")
    
    if user_id not in CONVERSATION_HISTORY:
        CONVERSATION_HISTORY[user_id] = []
    
    await update.message.reply_text(
        f"💬 *Mode chat activé* - {CHAT_MODES[USER_CHAT_MODES[user_id]]}\n\n"
        "Vous pouvez maintenant discuter avec moi à propos de vidéos YouTube.\n"
        "Envoyez `/chat_mode` pour changer de mode de conversation.\n"
        "Envoyez `/reset` pour effacer l'historique de conversation.\n"
        "Envoyez n'importe quel message pour continuer la conversation.",
        parse_mode="Markdown"
    )

async def handle_chat_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Basculer entre les modes disponibles
    current_mode = USER_CHAT_MODES.get(user_id, "libre")
    new_mode = "guidé" if current_mode == "libre" else "libre"
    USER_CHAT_MODES[user_id] = new_mode
    
    await update.message.reply_text(
        f"🔄 *Mode de conversation modifié*\n\n"
        f"Nouveau mode : {CHAT_MODES[new_mode]}",
        parse_mode="Markdown"
    )

async def handle_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    CONVERSATION_HISTORY[user_id] = []
    
    await update.message.reply_text(
        "🗑️ *Historique de conversation effacé*\n\n"
        "Votre conversation a été réinitialisée.",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    
    # Vérifier si le mode chat est actif
    if user_id in CHAT_ACTIVE and CHAT_ACTIVE[user_id]:
        # Ajouter le message de l'utilisateur à l'historique
        if user_id not in CONVERSATION_HISTORY:
            CONVERSATION_HISTORY[user_id] = []
        
        CONVERSATION_HISTORY[user_id].append({"role": "user", "content": message_text})
        
        # Si le message contient un lien YouTube, on récupère les sous-titres
        video_id = extract_video_id(message_text)
        context_content = ""
        
        if video_id:
            subtitles, error = get_subtitles(message_text)
            if error:
                await update.message.reply_text(error)
                return
            context_content = f"Sous-titres de la vidéo : {subtitles}"
        
        # Construire les messages pour l'IA
        messages = [
            {"role": "system", "content": f"Tu es un assistant qui aide à comprendre et analyser des vidéos YouTube. {context_content}"}
        ]
        
        # Ajouter l'historique de conversation limitée aux 10 derniers messages
        messages.extend(CONVERSATION_HISTORY[user_id][-10:])
        
        # Obtenir la réponse
        response = chat_with_lmstudio(messages)
        
        # Ajouter la réponse à l'historique
        CONVERSATION_HISTORY[user_id].append({"role": "assistant", "content": response})
        
        # Envoyer la réponse
        await update.message.reply_text(response)
        return
    
    # Comportement normal (non-chat) : résumé de vidéo YouTube
    url = message_text
    subtitles, error = get_subtitles(url)
    if error:
        await update.message.reply_text(error)
        return

    summary = summarize(subtitles)
    await update.message.reply_text(summary)

    audio_path = text_to_audio(summary)
    with open(audio_path, 'rb') as audio_file:
        await update.message.reply_voice(voice=audio_file)
    
    # Supprimer le fichier audio après l'envoi
    if os.path.exists(audio_path):
        os.remove(audio_path)

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    message_parts = message_text.split(" ", 1)
    
    if len(message_parts) < 2:
        await update.message.reply_text(
            "❗ Utilisation : `/question [lien YouTube] [votre question]`\n\n"
            "Exemple : `/question https://youtube.com/watch?v=VIDEO_ID Quelle est la conclusion principale ?`",
            parse_mode="Markdown"
        )
        return
    
    remaining_text = message_parts[1].strip()
    
    # Extraire l'URL et la question
    words = remaining_text.split()
    url = None
    question_words = []
    
    for word in words:
        if "youtube.com" in word or "youtu.be" in word:
            url = word
        else:
            question_words.append(word)
    
    if not url:
        await update.message.reply_text(
            "❌ Je n'ai pas trouvé d'URL YouTube valide dans votre message.\n\n"
            "Veuillez inclure un lien YouTube dans votre requête.",
            parse_mode="Markdown"
        )
        return
    
    question = " ".join(question_words).strip()
    
    if not question:
        await update.message.reply_text(
            "❓ Vous n'avez pas posé de question. Que souhaitez-vous savoir sur cette vidéo ?",
            parse_mode="Markdown"
        )
        return
    
    # Afficher un message d'attente
    processing_message = await update.message.reply_text(
        "⏳ Je récupère les sous-titres et analyse la vidéo...",
        parse_mode="Markdown"
    )
    
    # Récupérer les sous-titres
    subtitles, error = get_subtitles(url)
    if error:
        await processing_message.edit_text(
            f"❌ {error}",
            parse_mode="Markdown"
        )
        return
    
    await processing_message.edit_text(
        "⏳ J'analyse la vidéo et prépare une réponse à votre question...",
        parse_mode="Markdown"
    )
    
    # Répondre à la question
    answer = ask_question_about_subtitles(subtitles, question)
    
    # Supprimer le message d'attente et envoyer la réponse
    await processing_message.delete()
    await update.message.reply_text(
        f"*Question* : {question}\n\n{answer}",
        parse_mode="Markdown"
    )

async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🤖 *Bot YouTube Telegram* 🤖

Ce bot vous permet d'interagir avec des vidéos YouTube de façon intelligente.

📋 *Commandes disponibles* :

• `/start` - Démarrer le bot
• `/help` ou `/h` - Afficher ce message d'aide

*Résumé et questions* :
• Envoyez un lien YouTube pour obtenir un résumé
• `/question` ou `/q` - Poser une question sur une vidéo

*Mode conversation* :
• `/chat` ou `/c` - Activer le mode conversation
• `/mode` - Changer le mode conversation (libre/guidé)
• `/reset` ou `/r` - Effacer l'historique de conversation

*Abonnements* :
• `/subscribe` ou `/sub` - S'abonner à une chaîne
• `/unsubscribe` ou `/unsub` - Se désabonner
• `/list` ou `/subs` - Voir vos abonnements

📝 *Exemples* :
1. Résumé : envoyez simplement un lien YouTube
2. Question : `/q https://youtube.com/watch?v=VIDEO_ID Quelle est la conclusion ?`
3. Abonnement : `/sub https://www.youtube.com/@NomDeLaChaine`
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
👋 *Bienvenue sur le Bot YouTube Telegram* !

Ce bot vous aide à obtenir des résumés et à poser des questions sur des vidéos YouTube grâce à l'intelligence artificielle.

🔍 *Pour commencer* :
• Envoyez simplement un lien YouTube pour obtenir un résumé
• Utilisez `/help` pour voir toutes les commandes disponibles

Bonne utilisation ! 🚀
"""
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_parts = update.message.text.split(" ", 1)
    
    if len(message_parts) < 2:
        await update.message.reply_text(
            "❗ Utilisation : `/subscribe [URL chaîne YouTube]`\n\n"
            "Exemple : `/subscribe https://www.youtube.com/@NomDeLaChaine`",
            parse_mode="Markdown"
        )
        return
    
    channel_url = message_parts[1].strip()
    
    # Vérifier si c'est une URL YouTube valide
    if "youtube.com" not in channel_url and "youtu.be" not in channel_url:
        await update.message.reply_text(
            "❌ L'URL fournie n'est pas une URL YouTube valide.\n\n"
            "Exemple d'URL valide : `https://www.youtube.com/@NomDeLaChaine`",
            parse_mode="Markdown"
        )
        return
    
    # Obtenir les informations de la chaîne
    channel_info = get_channel_info(channel_url)
    
    if not channel_info:
        await update.message.reply_text(
            "❌ Impossible d'obtenir les informations de cette chaîne.\n\n"
            "Assurez-vous que l'URL est correcte.",
            parse_mode="Markdown"
        )
        return
    
    # Initialiser la structure pour l'utilisateur si nécessaire
    if user_id not in CHANNEL_SUBSCRIPTIONS:
        CHANNEL_SUBSCRIPTIONS[user_id] = {}
    
    # Ajouter l'abonnement
    channel_id = channel_info["id"]
    channel_name = channel_info["name"]
    
    if channel_id in CHANNEL_SUBSCRIPTIONS[user_id]:
        await update.message.reply_text(
            f"ℹ️ Vous êtes déjà abonné à la chaîne *{channel_name}*.",
            parse_mode="Markdown"
        )
        return
    
    CHANNEL_SUBSCRIPTIONS[user_id][channel_id] = channel_name
    
    # Initialiser le suivi des dernières vidéos pour cette chaîne
    if channel_id not in LATEST_VIDEOS:
        LATEST_VIDEOS[channel_id] = []
    
    # Sauvegarder les abonnements
    save_subscriptions()
    
    await update.message.reply_text(
        f"✅ Vous êtes maintenant abonné à la chaîne *{channel_name}*.\n\n"
        "Vous recevrez des résumés des nouvelles vidéos publiées sur cette chaîne.",
        parse_mode="Markdown"
    )

async def handle_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_parts = update.message.text.split(" ", 1)
    
    if user_id not in CHANNEL_SUBSCRIPTIONS or not CHANNEL_SUBSCRIPTIONS[user_id]:
        await update.message.reply_text(
            "❗ Vous n'êtes abonné à aucune chaîne YouTube.",
            parse_mode="Markdown"
        )
        return
    
    if len(message_parts) < 2:
        # Liste les chaînes auxquelles l'utilisateur est abonné
        channels_list = "\n".join([f"• *{name}* - `/unsubscribe {channel_id}`" 
                                 for channel_id, name in CHANNEL_SUBSCRIPTIONS[user_id].items()])
        
        await update.message.reply_text(
            "❗ Utilisation : `/unsubscribe [ID chaîne YouTube]`\n\n"
            "Vos abonnements actuels :\n"
            f"{channels_list}\n\n"
            "Choisissez l'ID de la chaîne dont vous souhaitez vous désabonner.",
            parse_mode="Markdown"
        )
        return
    
    channel_id_or_url = message_parts[1].strip()
    
    # Vérifie si c'est une URL ou un ID
    if "youtube.com" in channel_id_or_url or "youtu.be" in channel_id_or_url:
        channel_info = get_channel_info(channel_id_or_url)
        if not channel_info:
            await update.message.reply_text(
                "❌ Impossible d'obtenir les informations de cette chaîne.\n\n"
                "Assurez-vous que l'URL est correcte.",
                parse_mode="Markdown"
            )
            return
        channel_id = channel_info["id"]
    else:
        channel_id = channel_id_or_url
    
    # Vérifie si l'utilisateur est abonné à cette chaîne
    if channel_id not in CHANNEL_SUBSCRIPTIONS[user_id]:
        await update.message.reply_text(
            "❌ Vous n'êtes pas abonné à cette chaîne.",
            parse_mode="Markdown"
        )
        return
    
    # Récupère le nom de la chaîne avant de supprimer
    channel_name = CHANNEL_SUBSCRIPTIONS[user_id][channel_id]
    
    # Supprime l'abonnement
    del CHANNEL_SUBSCRIPTIONS[user_id][channel_id]
    
    # Si l'utilisateur n'a plus d'abonnements, supprime son entrée
    if not CHANNEL_SUBSCRIPTIONS[user_id]:
        del CHANNEL_SUBSCRIPTIONS[user_id]
    
    # Sauvegarder les abonnements
    save_subscriptions()
    
    await update.message.reply_text(
        f"✅ Vous êtes maintenant désabonné de la chaîne *{channel_name}*.",
        parse_mode="Markdown"
    )

async def handle_list_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in CHANNEL_SUBSCRIPTIONS or not CHANNEL_SUBSCRIPTIONS[user_id]:
        await update.message.reply_text(
            "ℹ️ Vous n'êtes abonné à aucune chaîne YouTube.",
            parse_mode="Markdown"
        )
        return
    
    channels_list = "\n".join([f"• *{name}* (`{channel_id}`)" 
                             for channel_id, name in CHANNEL_SUBSCRIPTIONS[user_id].items()])
    
    await update.message.reply_text(
        "📋 *Vos abonnements actuels* :\n\n"
        f"{channels_list}\n\n"
        "Pour vous désabonner d'une chaîne, utilisez :\n"
        "`/unsubscribe [ID chaîne]`",
        parse_mode="Markdown"
    )

# --- Lancement du bot ---
if __name__ == '__main__':
    # Vérification de la configuration
    print("\n=== Vérification de la configuration au démarrage ===")
    config_ok = True
    
    if not TELEGRAM_TOKEN:
        print("❌ ERREUR: Token Telegram non défini dans le fichier .env")
        config_ok = False
    
    if not LM_API_URL:
        print("❌ ERREUR: URL de l'API LM non définie dans le fichier .env")
        config_ok = False
    
    if not LM_MODEL_NAME:
        print("❌ ERREUR: Nom du modèle LM non défini dans le fichier .env")
        config_ok = False
        
    if not config_ok:
        print("\n⚠️ Le bot peut ne pas fonctionner correctement en raison de problèmes de configuration.")
        print("Veuillez vérifier le fichier .env et vous assurer que toutes les variables sont correctement définies.")
    else:
        print("✅ Configuration OK")
    
    print("=== Fin de la vérification ===\n")
    
    # Test de connexion à l'API LM
    if LM_API_URL and LM_MODEL_NAME:
        print("Test de connexion à l'API LM...")
        try:
            response = requests.post(
                LM_API_URL, 
                json={
                    "model": LM_MODEL_NAME,
                    "messages": [{"role": "user", "content": "test"}],
                    "temperature": 0.7,
                    "stream": False
                },
                timeout=5
            )
            if response.status_code == 200:
                print("✅ Connexion à l'API LM établie avec succès")
            else:
                print(f"❌ Erreur de connexion à l'API LM: Code {response.status_code}")
        except Exception as e:
            print(f"❌ Erreur de connexion à l'API LM: {str(e)}")
    
    # Charger les abonnements existants
    load_subscriptions()
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Handler principal
    app.add_handler(CommandHandler("question", handle_question))
    app.add_handler(CommandHandler("q", handle_question))  # Alias court pour question
    
    # Commandes d'aide et de démarrage
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("h", handle_help))  # Alias court pour help
    app.add_handler(CommandHandler("start", handle_start))
    
    # Commandes chat
    app.add_handler(CommandHandler("chat", handle_chat))
    app.add_handler(CommandHandler("c", handle_chat))  # Alias court pour chat
    app.add_handler(CommandHandler("chat_mode", handle_chat_mode))
    app.add_handler(CommandHandler("mode", handle_chat_mode))  # Alias plus intuitif
    app.add_handler(CommandHandler("reset", handle_reset))
    app.add_handler(CommandHandler("r", handle_reset))  # Alias court pour reset
    
    # Commandes d'abonnement
    app.add_handler(CommandHandler("subscribe", handle_subscribe))
    app.add_handler(CommandHandler("sub", handle_subscribe))  # Alias court pour subscribe
    app.add_handler(CommandHandler("unsubscribe", handle_unsubscribe))
    app.add_handler(CommandHandler("unsub", handle_unsubscribe))  # Alias court pour unsubscribe
    app.add_handler(CommandHandler("list_subscriptions", handle_list_subscriptions))
    app.add_handler(CommandHandler("list", handle_list_subscriptions))  # Alias court pour list_subscriptions
    app.add_handler(CommandHandler("subs", handle_list_subscriptions))  # Alias court pour list_subscriptions
    
    # Démarrer le planificateur
    scheduler_status = start_video_check_scheduler(app)
    if scheduler_status:
        print("✅ Planificateur de vérification des vidéos démarré")
    else:
        print("⚠️ Planificateur non disponible, vérification automatique désactivée")
    
    # Démarrage du bot
    print("Bot démarré !")
    app.run_polling()
