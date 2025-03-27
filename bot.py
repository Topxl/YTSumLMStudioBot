import os
import re
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled
from gtts import gTTS

# --- Config ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

LM_API_URL = "http://192.168.1.38:1234/v1/chat/completions"
LM_MODEL_NAME = "DeepSeek R1 Distill Qwen 7B"

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
        response = requests.post(LM_API_URL, json={
            "model": LM_MODEL_NAME,
            "messages": messages,
            "temperature": 0.7,
            "stream": False
        })

        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            return f"[Erreur LM Studio] Code {response.status_code} : {response.text}"
    except Exception as e:
        return f"[Erreur LM Studio] {str(e)}"

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
        "Fusionne-les en un résumé clair, structuré et synthétique en 5 points, "
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

# --- Handlers Telegram ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    subtitles, error = get_subtitles(url)
    if error:
        await update.message.reply_text(error)
        return

    summary = summarize(subtitles)
    await update.message.reply_text(summary)

    audio_path = text_to_audio(summary)
    with open(audio_path, 'rb') as audio_file:
        await update.message.reply_voice(voice=audio_file)

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    full_text = update.message.text
    parts = full_text.split(" ", 1)
    if len(parts) < 2:
        await update.message.reply_text("❗ Utilisation : /question [lien YouTube] ? [votre question]")
        return

    if "?" not in parts[1]:
        await update.message.reply_text("❗ Merci d'ajouter une question après le lien, séparée par un `?`")
        return

    url_part, question = parts[1].split("?", 1)
    url = url_part.strip()
    question = question.strip()

    subtitles, error = get_subtitles(url)
    if error:
        await update.message.reply_text(error)
        return

    answer = ask_question_about_subtitles(subtitles, question)
    await update.message.reply_text(answer)

# --- Lancement du bot ---
if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("question", handle_question))
    app.run_polling()
