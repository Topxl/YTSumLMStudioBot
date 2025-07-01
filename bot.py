import os
import re
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import yt_dlp
from gtts import gTTS
import json
import urllib.parse
from datetime import datetime
from googleapiclient.discovery import build
import time
import asyncio
import telegram
import xml.etree.ElementTree as ET

# --- Config ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LM_API_URL = os.getenv("LM_API_URL")

# Variables globales pour stocker la configuration détectée automatiquement
DETECTED_MODEL = None
DETECTED_CONTEXT_LENGTH = None
DETECTED_MAX_TOKENS = None

# Fonction pour détecter automatiquement le modèle et sa configuration
def detect_available_model():
    """Détecte automatiquement le modèle disponible dans LM Studio"""
    global DETECTED_MODEL
    
    if not LM_API_URL:
        print("❌ Erreur: LM_API_URL non défini")
        return None
    
    api_url = LM_API_URL.rstrip('/')
    models_endpoint = f"{api_url}/v1/models"
    
    try:
        print(f"🔍 Recherche des modèles disponibles sur {models_endpoint}")
        response = requests.get(models_endpoint, timeout=10)
        
        if response.status_code == 200:
            models_data = response.json()
            
            if 'data' in models_data and len(models_data['data']) > 0:
                # Prendre le premier modèle disponible
                model_id = models_data['data'][0]['id']
                DETECTED_MODEL = model_id
                print(f"✅ Modèle détecté automatiquement: {model_id}")
                
                # Détecter la configuration du modèle
                detect_model_configuration(model_id)
                return model_id
            else:
                print("❌ Aucun modèle trouvé dans la réponse")
                return None
        else:
            print(f"❌ Erreur lors de la récupération des modèles: {response.status_code}")
            return None
            
    except requests.exceptions.ConnectionError:
        print("❌ Erreur de connexion: Impossible de se connecter à LM Studio")
        return None
    except Exception as e:
        print(f"❌ Erreur lors de la détection du modèle: {str(e)}")
        return None

def detect_model_configuration(model_id):
    """Détecte automatiquement la configuration du modèle (contexte, max tokens)"""
    global DETECTED_CONTEXT_LENGTH, DETECTED_MAX_TOKENS
    
    api_url = LM_API_URL.rstrip('/')
    chat_endpoint = f"{api_url}/v1/chat/completions"
    
    try:
        print(f"🔧 Détection avancée de la configuration du modèle {model_id}...")
        
        # Tests progressifs pour trouver la vraie limite
        test_sizes = [
            (500, "Test court. " * 50),        # ~500 tokens
            (2000, "Test moyen. " * 200),      # ~2000 tokens  
            (4000, "Test long. " * 400),       # ~4000 tokens
            (8000, "Test très long. " * 800),  # ~8000 tokens
            (12000, "Test énorme. " * 1200),   # ~12000 tokens
            (16000, "Test géant. " * 1600),    # ~16000 tokens
            (20000, "Test massif. " * 2000),   # ~20000 tokens
            (32000, "Test colossal. " * 3200), # ~32000 tokens
            (50000, "Test titanesque. " * 5000), # ~50000 tokens
            (75000, "Test gigantesque. " * 7500), # ~75000 tokens
            (100000, "Test astronomique. " * 10000), # ~100000 tokens
        ]
        
        max_working_size = 500  # Au minimum 500 tokens
        
        for expected_tokens, test_content in test_sizes:
            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": test_content}],
                "max_tokens": 10,  # Très peu pour la réponse
                "temperature": 0.1
            }
            
            print(f"   🧪 Test avec ~{expected_tokens} tokens...", end="")
            # Timeout plus long pour les gros tests
            timeout = 30 if expected_tokens > 50000 else 20 if expected_tokens > 20000 else 15
            response = requests.post(chat_endpoint, json=payload, timeout=timeout)
            
            if response.status_code == 200:
                max_working_size = expected_tokens
                print(" ✅")
            else:
                print(" ❌")
                # Analyser l'erreur pour comprendre la limite exacte
                error_text = response.text.lower()
                if "context" in error_text:
                    # Chercher des nombres dans l'erreur pour extraire la limite réelle
                    import re
                    numbers = re.findall(r'\b(\d+)\b', error_text)
                    if numbers:
                        # Prendre le plus grand nombre trouvé comme limite probable
                        context_limits = [int(n) for n in numbers if int(n) > 1000]
                        if context_limits:
                            detected_limit = max(context_limits)
                            print(f"   📊 Limite détectée dans l'erreur: {detected_limit} tokens")
                            # Utiliser 80% de la limite détectée pour la sécurité
                            max_working_size = min(max_working_size, int(detected_limit * 0.8))
                break
        
        # Définir la configuration basée sur la taille maximale qui fonctionne
        if max_working_size >= 75000:
            DETECTED_CONTEXT_LENGTH = 90000  # Pour les modèles astronomiques (100k+)
            DETECTED_MAX_TOKENS = 8000
            print(f"✅ Modèle astronomique détecté:")
        elif max_working_size >= 50000:
            DETECTED_CONTEXT_LENGTH = 60000  # Pour les modèles titanesques (75k+)
            DETECTED_MAX_TOKENS = 6000
            print(f"✅ Modèle titanesque détecté:")
        elif max_working_size >= 32000:
            DETECTED_CONTEXT_LENGTH = 40000  # Pour les modèles colossaux (50k+)
            DETECTED_MAX_TOKENS = 4000
            print(f"✅ Modèle colossal détecté:")
        elif max_working_size >= 20000:
            DETECTED_CONTEXT_LENGTH = 16000  # Pour les modèles massifs (conservative)
            DETECTED_MAX_TOKENS = 2000
            print(f"✅ Modèle massif détecté:")
        elif max_working_size >= 16000:
            DETECTED_CONTEXT_LENGTH = 12000  # Pour les modèles géants (conservative)
            DETECTED_MAX_TOKENS = 1500
            print(f"✅ Modèle géant détecté:")
        elif max_working_size >= 12000:
            DETECTED_CONTEXT_LENGTH = 15000  # Pour les très gros modèles (16k+)
            DETECTED_MAX_TOKENS = 2000
            print(f"✅ Modèle haute capacité détecté:")
        elif max_working_size >= 8000:
            DETECTED_CONTEXT_LENGTH = 10000  # Pour les gros modèles (12k+)
            DETECTED_MAX_TOKENS = 1500
            print(f"✅ Modèle grande capacité détecté:")
        elif max_working_size >= 4000:
            DETECTED_CONTEXT_LENGTH = 6000   # Pour les modèles moyens-hauts (8k+)
            DETECTED_MAX_TOKENS = 1000
            print(f"✅ Modèle moyenne-haute capacité détecté:")
        elif max_working_size >= 2000:
            DETECTED_CONTEXT_LENGTH = 3000   # Pour les modèles moyens (4k+)
            DETECTED_MAX_TOKENS = 800
            print(f"✅ Modèle moyenne capacité détecté:")
        else:
            DETECTED_CONTEXT_LENGTH = 1500   # Pour les petits modèles
            DETECTED_MAX_TOKENS = 400
            print(f"✅ Modèle petite capacité détecté:")
            
        print(f"   📏 Contexte utilisé: {DETECTED_CONTEXT_LENGTH} tokens (testé jusqu'à {max_working_size})")
        print(f"   📝 Max tokens: {DETECTED_MAX_TOKENS}")
            
    except Exception as e:
        # Valeurs par défaut très conservatrices en cas d'erreur
        DETECTED_CONTEXT_LENGTH = 8000
        DETECTED_MAX_TOKENS = 1000
        print(f"❌ Erreur lors de la détection de configuration: {str(e)}")
        print(f"⚠️ Utilisation des valeurs par défaut:")
        print(f"   📏 Contexte: {DETECTED_CONTEXT_LENGTH} tokens")
        print(f"   📝 Max tokens: {DETECTED_MAX_TOKENS}")

def get_adaptive_chunk_size():
    """Retourne la taille de chunk adaptée à la configuration détectée"""
    if DETECTED_CONTEXT_LENGTH:
        # Adapter la taille des chunks selon la vraie capacité du modèle
        
        if DETECTED_CONTEXT_LENGTH >= 90000:
            # Pour les modèles astronomiques (90k+ tokens)
            chunk_size = 150000  # Chunks astronomiques
        elif DETECTED_CONTEXT_LENGTH >= 60000:
            # Pour les modèles titanesques (60k-90k tokens)
            chunk_size = 100000  # Chunks titanesques
        elif DETECTED_CONTEXT_LENGTH >= 40000:
            # Pour les modèles colossaux (40k-60k tokens)
            chunk_size = 70000   # Chunks colossaux
        elif DETECTED_CONTEXT_LENGTH >= 25000:
            # Pour les modèles massifs (25k-40k tokens)
            chunk_size = 30000   # Chunks massifs (plus conservateur)
        elif DETECTED_CONTEXT_LENGTH >= 16000:
            # Pour les modèles massifs (16k-25k tokens)
            chunk_size = 20000   # Chunks larges (plus conservateur)
        elif DETECTED_CONTEXT_LENGTH >= 12000:
            # Pour les modèles géants (12k-16k tokens)
            chunk_size = 15000   # Chunks moyens (plus conservateur)
        elif DETECTED_CONTEXT_LENGTH >= 15000:
            # Pour les très gros modèles (15k-20k tokens)
            chunk_size = 25000   # Chunks très larges
        elif DETECTED_CONTEXT_LENGTH >= 10000:
            # Pour les gros modèles (10k-15k tokens)
            chunk_size = 18000   # Chunks larges
        elif DETECTED_CONTEXT_LENGTH >= 6000:
            # Pour les modèles moyens-hauts (6k-10k tokens)
            chunk_size = 12000   # Chunks moyens-larges
        elif DETECTED_CONTEXT_LENGTH >= 3000:
            # Pour les modèles moyens (3k-6k tokens)
            chunk_size = 8000    # Chunks moyens
        elif DETECTED_CONTEXT_LENGTH >= 2000:
            # Pour les modèles petits-moyens (2k-3k tokens)
            chunk_size = 5000    # Chunks petits-moyens
        else:
            # Pour les petits modèles (moins de 2k tokens)
            chunk_size = 3000    # Chunks petits
        
        print(f"📐 Taille de chunk adaptée: {chunk_size} caractères (contexte détecté: {DETECTED_CONTEXT_LENGTH} tokens)")
        return chunk_size
    else:
        # Valeur par défaut plus conservatrice
        print(f"📐 Taille de chunk par défaut: 12000 caractères (contexte non détecté)")
        return 12000

def test_lm_studio_connection():
    """Teste la connexion avec LM Studio et détecte le modèle disponible"""
    if not LM_API_URL:
        return False
    
    # D'abord détecter le modèle disponible
    model = detect_available_model()
    if not model:
        return False
    
    # Ensuite tester une requête simple
    api_url = LM_API_URL.rstrip('/')
    chat_endpoint = f"{api_url}/v1/chat/completions"
    
    try:
        # Requête simple pour tester l'API
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Test"}],
            "max_tokens": 5,
            "temperature": 0.1
        }
        
        response = requests.post(chat_endpoint, json=payload, timeout=10)
        return response.status_code == 200
    except:
        return False

# Fonction pour vérifier la disponibilité de LM Studio
def check_lmstudio_availability():
    """Vérifie si LM Studio est accessible et configuré correctement"""
    if not LM_API_URL:
        print("❌ Erreur: LM_API_URL non défini dans le fichier .env")
        return False
    
    # Tester la connexion et détecter automatiquement le modèle
    if test_lm_studio_connection():
        print(f"✅ Connexion à LM Studio réussie sur {LM_API_URL}!")
        if DETECTED_MODEL:
            print(f"✅ Modèle détecté et prêt: {DETECTED_MODEL}")
        return True
    else:
        print("❌ Erreur: Impossible de se connecter à LM Studio. Vérifiez que le serveur est bien lancé.")
        return False

print("=== Configuration chargée ===")
print(f"TELEGRAM_TOKEN: {TELEGRAM_TOKEN[:10]}..." if TELEGRAM_TOKEN else "TELEGRAM_TOKEN non défini")
print(f"LM_API_URL: {LM_API_URL}" if LM_API_URL else "LM_API_URL non défini")
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

# File d'attente pour les liens YouTube à traiter
# Format: {"chat_id": {"queue": [urls], "processing": False, "thread_id": None}}
YOUTUBE_QUEUE = {}

# --- Utilitaires ---

def extract_video_id(url):
    # Nettoyer l'URL d'abord
    clean_url = url.split('$')[0].strip()
    
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11})",
        r"youtu\.be\/([0-9A-Za-z_-]{11})"
    ]
    for pattern in patterns:
        match = re.search(pattern, clean_url)
        if match:
            video_id = match.group(1)
            # Nettoyer l'ID vidéo de tout caractère parasite
            clean_video_id = re.sub(r'[^0-9A-Za-z_-]', '', video_id)[:11]
            return clean_video_id
    return None

def clean_subtitle_text(subtitle_content):
    """Nettoie le contenu des sous-titres (XML, VTT, etc.) pour extraire le texte pur"""
    try:
        import re
        import html
        
        print(f"🧹 Début du nettoyage des sous-titres ({len(subtitle_content)} caractères)")
        
        # Si c'est du XML (format YouTube)
        if subtitle_content.strip().startswith('<?xml') or '<transcript>' in subtitle_content:
            print("🧹 Nettoyage des sous-titres XML...")
            # Extraire le texte entre les balises <text>
            text_matches = re.findall(r'<text[^>]*>(.*?)</text>', subtitle_content, re.DOTALL)
            if text_matches:
                # Joindre tous les textes et nettoyer les entités HTML
                full_text = ' '.join(text_matches)
                # Décoder les entités HTML
                full_text = html.unescape(full_text)
                # Nettoyer les balises HTML restantes
                full_text = re.sub(r'<[^>]+>', '', full_text)
                # Nettoyer les espaces multiples
                full_text = re.sub(r'\s+', ' ', full_text).strip()
                print(f"✅ XML nettoyé: {len(full_text)} caractères")
                return full_text
        
        # Si c'est du VTT
        elif 'WEBVTT' in subtitle_content:
            print("🧹 Nettoyage des sous-titres VTT...")
            lines = subtitle_content.split('\n')
            text_lines = []
            for line in lines:
                line = line.strip()
                # Ignorer les lignes de timing et les métadonnées
                if (line and 
                    not line.startswith('WEBVTT') and 
                    not '-->' in line and 
                    not line.isdigit() and
                    not line.startswith('NOTE') and
                    not line.startswith('Kind:') and
                    not line.startswith('Language:')):
                    # Nettoyer les balises de formatage VTT
                    line = re.sub(r'<[^>]+>', '', line)
                    # Décoder les entités HTML
                    line = html.unescape(line)
                    if line.strip():
                        text_lines.append(line)
            
            full_text = ' '.join(text_lines)
            # Nettoyer les espaces multiples
            full_text = re.sub(r'\s+', ' ', full_text).strip()
            print(f"✅ VTT nettoyé: {len(full_text)} caractères")
            return full_text
        
        # Si c'est déjà du texte pur, le nettoyer quand même
        else:
            print("🧹 Nettoyage du texte brut...")
            
            # Vérifier si c'est des métadonnées JSON (sous-titres automatiques)
            if ('acAsrConf' in subtitle_content or 'tOffsetMs' in subtitle_content or 
                'dDurationMs' in subtitle_content or 'tStartMs' in subtitle_content):
                print("🚨 Métadonnées JSON détectées - extraction du texte parlé uniquement")
                
                # Essayer d'extraire le JSON et récupérer le texte
                try:
                    import json
                    # Si c'est un array JSON
                    if subtitle_content.strip().startswith('['):
                        data = json.loads(subtitle_content)
                        if isinstance(data, list):
                            text_parts = []
                            for item in data:
                                # Chercher le texte dans différentes propriétés possibles
                                if isinstance(item, dict):
                                    for key in ['text', 'content', 'transcript', 'caption']:
                                        if key in item and isinstance(item[key], str):
                                            text_parts.append(item[key])
                                            break
                            if text_parts:
                                cleaned_text = ' '.join(text_parts)
                                print(f"✅ Texte extrait du JSON: {len(cleaned_text)} caractères")
                                return cleaned_text
                except:
                    pass
                
                # Si l'extraction JSON échoue, filtrer manuellement les métadonnées
                lines = subtitle_content.split('\n')
                text_lines = []
                for line in lines:
                    line = line.strip()
                    # Ignorer les lignes contenant des métadonnées
                    if (line and 
                        not 'acAsrConf' in line and
                        not 'tOffsetMs' in line and 
                        not 'dDurationMs' in line and
                        not 'tStartMs' in line and
                        not line.startswith('{') and
                        not line.startswith('"ac') and
                        not line.startswith('"t') and
                        not line.startswith('"d') and
                        not '":' in line and
                        not line.endswith(',') and
                        not line.endswith('}') and
                        not line in ['{', '}', '[', ']']):
                        # Nettoyer les guillemets et caractères JSON restants
                        line = re.sub(r'^"([^"]*)"$', r'\1', line)  # Enlever guillemets autour
                        line = line.replace('\\"', '"')  # Corriger les guillemets échappés
                        if line and len(line) > 3:  # Ignorer les très courtes chaînes
                            text_lines.append(line)
                
                cleaned_text = ' '.join(text_lines)
                if cleaned_text:
                    print(f"✅ Métadonnées filtrées: {len(cleaned_text)} caractères")
                    return cleaned_text
                else:
                    print("❌ Impossible d'extraire le texte des métadonnées")
                    return "Erreur: contenu principalement composé de métadonnées techniques"
            
            # Nettoyage standard pour les autres formats
            # Décoder les entités HTML au cas où
            cleaned_text = html.unescape(subtitle_content)
            # Nettoyer les balises HTML
            cleaned_text = re.sub(r'<[^>]+>', '', cleaned_text)
            # Nettoyer les caractères de contrôle et les caractères non imprimables
            cleaned_text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', cleaned_text)
            # Nettoyer les caractères Unicode problématiques
            cleaned_text = re.sub(r'[^\w\s\.,;:!?\-\'\"()[\]{}]', ' ', cleaned_text)
            # Nettoyer les espaces multiples
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
            
            # Vérifier si le texte semble corrompu (trop de caractères étranges)
            if len(cleaned_text) > 0:
                # Calculer le ratio de caractères alphabétiques
                alpha_chars = sum(1 for c in cleaned_text if c.isalpha())
                total_chars = len(cleaned_text.replace(' ', ''))
                if total_chars > 0:
                    alpha_ratio = alpha_chars / total_chars
                    if alpha_ratio < 0.5:  # Moins de 50% de caractères alphabétiques
                        print(f"⚠️ Texte possiblement corrompu (ratio alphabétique: {alpha_ratio:.2f})")
                        print(f"Échantillon: {cleaned_text[:200]}...")
            
            print(f"✅ Texte brut nettoyé: {len(cleaned_text)} caractères")
            return cleaned_text
            
    except Exception as e:
        print(f"⚠️ Erreur lors du nettoyage des sous-titres: {e}")
        return subtitle_content

def get_subtitles_with_ytdlp(video_url):
    """Méthode alternative pour récupérer les sous-titres avec yt-dlp"""
    try:
        print("🔄 Tentative de récupération des sous-titres avec yt-dlp...")
        
        ydl_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['fr', 'en'],
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            # Chercher les sous-titres français d'abord
            if 'subtitles' in info and info['subtitles']:
                if 'fr' in info['subtitles']:
                    print("🇫🇷 Sous-titres français trouvés avec yt-dlp")
                    subtitle_url = info['subtitles']['fr'][0]['url']
                    response = requests.get(subtitle_url)
                    cleaned_text = clean_subtitle_text(response.text)
                    return cleaned_text, None
                elif 'en' in info['subtitles']:
                    print("🇬🇧 Sous-titres anglais trouvés avec yt-dlp")
                    subtitle_url = info['subtitles']['en'][0]['url']
                    response = requests.get(subtitle_url)
                    cleaned_text = clean_subtitle_text(response.text)
                    return cleaned_text, None
            
            # Essayer les sous-titres automatiques
            if 'automatic_captions' in info and info['automatic_captions']:
                if 'fr' in info['automatic_captions']:
                    print("🤖 Sous-titres automatiques français trouvés avec yt-dlp")
                    subtitle_url = info['automatic_captions']['fr'][0]['url']
                    response = requests.get(subtitle_url)
                    cleaned_text = clean_subtitle_text(response.text)
                    
                    # Vérifier si le texte est vraiment en français ou si c'est de l'anglais étiqueté comme français
                    if cleaned_text and len(cleaned_text) > 100:
                        # Test simple : si beaucoup de mots anglais courants, c'est probablement de l'anglais
                        english_words = ['the', 'and', 'that', 'this', 'with', 'for', 'are', 'was', 'but', 'not', 'you', 'all', 'can', 'had', 'her', 'his', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'way', 'who', 'boy', 'did', 'she', 'use', 'her', 'how', 'oil', 'sit', 'set']
                        text_lower = cleaned_text.lower()
                        english_count = sum(1 for word in english_words if f' {word} ' in text_lower)
                        
                        if english_count > 20:  # Si beaucoup de mots anglais détectés
                            print("🔍 Contenu détecté comme anglais malgré l'étiquette française - Traduction requise")
                            return cleaned_text, "translate_needed"
                    
                    return cleaned_text, None
                elif 'en' in info['automatic_captions']:
                    print("🤖 Sous-titres automatiques anglais trouvés avec yt-dlp")
                    subtitle_url = info['automatic_captions']['en'][0]['url']
                    response = requests.get(subtitle_url)
                    cleaned_text = clean_subtitle_text(response.text)
                    return cleaned_text, "translate_needed"
        
        return None, "[Erreur] Aucun sous-titre trouvé avec yt-dlp"
        
    except Exception as e:
        print(f"❌ Erreur avec yt-dlp: {str(e)}")
        return None, f"[Erreur yt-dlp] {str(e)}"

def translate_to_french(english_text):
    """Traduit un texte anglais vers le français en utilisant LM Studio"""
    try:
        print(f"🔄 Traduction du texte anglais vers le français ({len(english_text)} caractères)...")
        
        # Pour les très longs textes, traduire par chunks
        if len(english_text) > 15000:
            print("📄 Texte très long - traduction par parties...")
            chunks = split_text(english_text, 15000)
            translated_chunks = []
            
            for i, chunk in enumerate(chunks):
                print(f"   Traduction partie {i+1}/{len(chunks)}...")
                messages = [
                    {"role": "system", "content": "Tu es un traducteur professionnel. Traduis fidèlement ce texte anglais vers le français. Garde le sens et le style original. Ne traduis que le contenu, n'ajoute aucun commentaire."},
                    {"role": "user", "content": f"Traduis ce texte en français :\n\n{chunk}"}
                ]
                
                translated_chunk = chat_with_lmstudio(messages)
                if not translated_chunk.startswith("[Erreur"):
                    translated_chunks.append(translated_chunk)
                else:
                    print(f"⚠️ Erreur de traduction pour la partie {i+1}, conservation de l'original")
                    translated_chunks.append(chunk)
            
            result = " ".join(translated_chunks)
            print(f"✅ Traduction complète effectuée: {len(result)} caractères")
            return result
        else:
            # Traduction directe pour les textes courts
            messages = [
                {"role": "system", "content": "Tu es un traducteur professionnel. Traduis fidèlement ce texte anglais vers le français. Garde le sens et le style original. Ne traduis que le contenu, n'ajoute aucun commentaire."},
                {"role": "user", "content": f"Traduis ce texte en français :\n\n{english_text}"}
            ]
            
            translated_text = chat_with_lmstudio(messages)
            if not translated_text.startswith("[Erreur"):
                print(f"✅ Traduction effectuée: {len(translated_text)} caractères")
                return translated_text
            else:
                print(f"⚠️ Erreur de traduction, conservation du texte original")
                return english_text
                
    except Exception as e:
        print(f"❌ Erreur lors de la traduction: {str(e)}")
        return english_text

def get_subtitles(video_url):
    try:
        video_id = extract_video_id(video_url)
        if not video_id:
            return None, "[Erreur] Lien invalide ou ID introuvable."

        print(f"🔍 Récupération des sous-titres pour la vidéo ID: {video_id}")
        
        # Nettoyer l'URL si elle contient des caractères parasites
        clean_video_id = video_id.split('$')[0].split('&')[0].split('?')[0]
        print(f"🧹 ID vidéo nettoyé: {clean_video_id}")
        
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(clean_video_id)
            print(f"📋 Transcriptions disponibles: {[t.language_code for t in transcript_list]}")

            # Essayer d'abord le français
            for transcript in transcript_list:
                if transcript.language_code == "fr":
                    print("🇫🇷 Utilisation des sous-titres français")
                    entries = transcript.fetch()
                    return " ".join([entry['text'] for entry in entries]), None

            # Ensuite essayer les sous-titres traduisibles
            for transcript in transcript_list:
                if transcript.is_translatable:
                    print(f"🔄 Traduction depuis {transcript.language_code} vers le français")
                    translated = transcript.translate('fr')
                    entries = translated.fetch()
                    return " ".join([entry['text'] for entry in entries]), None

            # Si aucun sous-titre français ou traduisible, prendre le premier disponible
            if transcript_list:
                first_transcript = list(transcript_list)[0]
                print(f"⚠️ Utilisation des sous-titres en {first_transcript.language_code} (non traduits)")
                entries = first_transcript.fetch()
                return " ".join([entry['text'] for entry in entries]), None

        except Exception as transcript_error:
            print(f"❌ Erreur avec YouTubeTranscriptApi: {str(transcript_error)}")
            print("🔄 Tentative avec méthode alternative (yt-dlp)...")
            
            # Essayer la méthode alternative avec yt-dlp
            subtitles, error = get_subtitles_with_ytdlp(video_url)
            
            # Si une traduction est nécessaire
            if error == "translate_needed" and subtitles:
                print("🌐 Traduction automatique du contenu anglais vers le français...")
                translated_subtitles = translate_to_french(subtitles)
                return translated_subtitles, None
            
            return subtitles, error

        return None, "[Erreur] Aucun sous-titre utilisable ou traduisible trouvé."

    except TranscriptsDisabled:
        print("⚠️ Sous-titres désactivés, tentative avec yt-dlp...")
        subtitles, error = get_subtitles_with_ytdlp(video_url)
        if error == "translate_needed" and subtitles:
            print("🌐 Traduction automatique du contenu anglais vers le français...")
            translated_subtitles = translate_to_french(subtitles)
            return translated_subtitles, None
        return subtitles, error
    except NoTranscriptFound:
        print("⚠️ Aucun sous-titre trouvé, tentative avec yt-dlp...")
        subtitles, error = get_subtitles_with_ytdlp(video_url)
        if error == "translate_needed" and subtitles:
            print("🌐 Traduction automatique du contenu anglais vers le français...")
            translated_subtitles = translate_to_french(subtitles)
            return translated_subtitles, None
        return subtitles, error
    except Exception as e:
        print(f"❌ Erreur détaillée lors de la récupération des sous-titres: {str(e)}")
        print("🔄 Tentative avec méthode alternative (yt-dlp)...")
        subtitles, error = get_subtitles_with_ytdlp(video_url)
        if error == "translate_needed" and subtitles:
            print("🌐 Traduction automatique du contenu anglais vers le français...")
            translated_subtitles = translate_to_french(subtitles)
            return translated_subtitles, None
        return subtitles, error

def split_text(text, max_chars=6000):
    """
    Divise un texte en parties plus petites en essayant de respecter les phrases.
    
    Args:
        text (str): Le texte à diviser
        max_chars (int): Nombre maximum de caractères par partie
        
    Returns:
        list: Liste des parties du texte
    """
    print(f"Découpage du texte ({len(text)} caractères) en chunks de max {max_chars} caractères")
    
    # Si le texte est déjà assez court, le retourner tel quel
    if len(text) <= max_chars:
        return [text]
    
    # Estimer le nombre de tokens (règle approximative: environ 4 caractères par token)
    estimated_tokens = len(text) / 4
    
    # Si le texte est très long (dépasse la limite de contexte du modèle), réduire encore plus la taille
    context_limit = DETECTED_CONTEXT_LENGTH if DETECTED_CONTEXT_LENGTH else int(os.getenv("LM_CONTEXT_LENGTH", "4096"))
    if estimated_tokens > context_limit:
        # Calculer un facteur de réduction pour respecter la limite de contexte
        # Utiliser 75% de la limite pour laisser de la place aux instructions et à la réponse
        safe_limit = int(context_limit * 0.75)
        # Calculer la taille de chunk maximale en caractères
        adjusted_max_chars = int((safe_limit / estimated_tokens) * len(text))
        # Limiter à un minimum de 1000 caractères et un maximum de max_chars original
        adjusted_max_chars = max(1000, min(adjusted_max_chars, max_chars))
        print(f"Texte très long détecté ({estimated_tokens:.0f} tokens estimés). Ajustement de la taille maximale à {adjusted_max_chars} caractères")
        max_chars = adjusted_max_chars
        
    parts = []
    remaining_text = text
    
    while len(remaining_text) > max_chars:
        # Chercher une fin de phrase (point suivi d'un espace) dans la plage max_chars
        split_index = remaining_text[:max_chars].rfind(". ") + 1
        
        # Si pas de point trouvé, chercher d'autres délimiteurs possibles
        if split_index <= 1:
            # Essayer avec une virgule suivie d'un espace
            split_index = remaining_text[:max_chars].rfind(", ") + 1
            
        # Si toujours pas trouvé, chercher un saut de ligne
        if split_index <= 1:
            split_index = remaining_text[:max_chars].rfind("\n") + 1
            
        # Si aucun délimiteur naturel n'a été trouvé, couper au maximum autorisé
        if split_index <= 1:
            split_index = max_chars
        
        # Extraire la partie et l'ajouter à la liste
        parts.append(remaining_text[:split_index].strip())
        
        # Mettre à jour le texte restant
        remaining_text = remaining_text[split_index:].strip()
    
    # Ajouter le reste du texte s'il en reste
    if remaining_text:
        parts.append(remaining_text)
    
    print(f"Texte découpé en {len(parts)} parties")
    return parts

def chat_with_lmstudio(messages):
    try:
        # Vérifier si les variables d'environnement sont définies
        if not LM_API_URL:
            return "[Erreur] Variable d'environnement LM_API_URL non définie dans le fichier .env"
        
        # Détecter automatiquement le modèle si pas encore fait
        if not DETECTED_MODEL:
            if not detect_available_model():
                return "[Erreur] Impossible de détecter un modèle disponible dans LM Studio. Vérifiez qu'un modèle est chargé."
        
        # Ne pas re-tester la connexion si le modèle est déjà détecté
        # (évite la re-détection en boucle)
        
        # S'assurer que l'URL se termine par /v1/chat/completions
        api_url = LM_API_URL.rstrip('/')
        if not api_url.endswith('/v1/chat/completions'):
            api_url = f"{api_url}/v1/chat/completions"
        
        print(f"Envoi de requête à {api_url}")
        
        # Préparation des messages au format OpenAI
        formatted_messages = []
        for msg in messages:
            # S'assurer que le rôle est valide (system, user, assistant)
            if msg["role"] not in ["system", "user", "assistant"]:
                continue
            formatted_messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })
        
        # S'assurer qu'il y a au moins un message
        if not formatted_messages:
            return "[Erreur] Aucun message valide à envoyer"
        
        # Format de requête compatible avec LM Studio (API OpenAI)
        # Utiliser les paramètres détectés automatiquement
        max_tokens = DETECTED_MAX_TOKENS if DETECTED_MAX_TOKENS else int(os.getenv("LM_MAX_TOKENS", "500"))
        
        payload = {
            "model": DETECTED_MODEL,  # Utiliser le modèle détecté automatiquement
            "messages": formatted_messages,
            "temperature": float(os.getenv("LM_TEMPERATURE", "0.7")),
            "max_tokens": max_tokens,
            "stream": False
        }

        # Utiliser un timeout plus long pour les modèles lourds (augmenté à 5 minutes)
        response = requests.post(api_url, json=payload, timeout=300)  # 5 minutes de timeout (augmenté de 2 à 5 minutes)

        if response.status_code == 200:
            try:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    return result['choices'][0]['message']['content']
                else:
                    error_msg = "[Erreur LM Studio] Format de réponse invalide"
                    print(error_msg)
                    print(f"Réponse complète : {result}")
                    return error_msg
            except Exception as e:
                error_msg = f"[Erreur LM Studio] Erreur lors du parsing de la réponse: {str(e)}"
                print(error_msg)
                return error_msg
        else:
            # Afficher plus de détails sur l'erreur
            error_msg = f"[Erreur LM Studio] Code {response.status_code} : {response.text}"
            print(error_msg)
            return error_msg
    except requests.exceptions.Timeout:
        error_msg = "[Erreur LM Studio] Timeout de la requête. Le serveur prend trop de temps à répondre."
        print(error_msg)
        return error_msg
    except requests.exceptions.ConnectionError:
        error_msg = "[Erreur LM Studio] Erreur de connexion. Vérifiez que LM Studio est bien lancé et accessible."
        print(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"[Erreur LM Studio] {str(e)}"
        print(error_msg)
        return error_msg

def summarize(text):
    try:
        # Diviser le texte en chunks adaptatifs basés sur la configuration détectée
        max_chunk_size = get_adaptive_chunk_size()
        chunks = split_text(text, max_chunk_size)
        summaries = []

        prompt = (
            "Fais un résumé du contenu en français en apportant un maximum de valeur au lecteur. "
            "Commence par un titre accrocheur en français qui résume le sujet principal, suivi d'un tiret. "
            "Utilise des points clairs en français, sans répétition, et mets en avant les idées clés. "
            "N'utilise pas de formatage Markdown comme les astérisques, les crochets ou autres caractères spéciaux. "
            "IMPORTANT: Réponds uniquement en français, même si le contenu source était en anglais."
        )

        print(f"Traitement de {len(chunks)} chunks pour résumé...")
        
        # Pour les vidéos très longues, on peut avoir un nombre important de chunks
        if len(chunks) > 15:
            print(f"Vidéo très longue détectée ({len(chunks)} chunks). Utilisation d'une stratégie de résumé progressive.")
            
            # Première étape: résumer les chunks individuellement
            batch_summaries = []
            for i, chunk in enumerate(chunks):
                try:
                    print(f"Résumé du chunk {i+1}/{len(chunks)} (taille: {len(chunk)} caractères)")
                    messages = [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": chunk}
                    ]
                    
                    # Obtenir le résumé pour ce chunk
                    chunk_summary = chat_with_lmstudio(messages)
                    chunk_summary = sanitize_markdown(chunk_summary)
                    
                    # Vérifier si le résumé contient une erreur
                    if chunk_summary.startswith("[Erreur"):
                        print(f"Erreur lors du résumé du chunk {i+1}: {chunk_summary}")
                        # En cas d'erreur, simplifier la demande pour ce chunk
                        simplified_messages = [
                            {"role": "system", "content": "Résume ce texte en français simplement sans formatage, en quelques phrases clés."},
                            {"role": "user", "content": chunk[:len(chunk) // 2]}  # Utiliser moitié moins de texte
                        ]
                        chunk_summary = chat_with_lmstudio(simplified_messages)
                        chunk_summary = sanitize_markdown(chunk_summary)
                    
                    # Si toujours en erreur, utiliser un résumé générique
                    if chunk_summary.startswith("[Erreur"):
                        chunk_summary = f"[Contenu du segment {i+1} non traité]"
                    
                    batch_summaries.append(chunk_summary)
                except Exception as e:
                    print(f"Erreur lors du traitement du chunk {i+1}: {str(e)}")
                    batch_summaries.append(f"[Erreur dans le segment {i+1}]")
            
            # Deuxième étape: regrouper les résumés par lots de 5-7 et les fusionner
            intermediate_summaries = []
            batch_size = min(6, max(3, len(batch_summaries) // 5))  # Taille de lot dynamique
            
            for i in range(0, len(batch_summaries), batch_size):
                batch = batch_summaries[i:i+batch_size]
                batch_text = "\n\n".join([f"Section {i+j+1}: {summary}" for j, summary in enumerate(batch)])
                
                fusion_message = [
                    {"role": "system", "content": "Fusionne ces résumés partiels en un seul résumé cohérent en français sans formatage. Garde les points clés principaux uniquement. Réponds uniquement en français."},
                    {"role": "user", "content": batch_text}
                ]
                
                try:
                    batch_summary = chat_with_lmstudio(fusion_message)
                    batch_summary = sanitize_markdown(batch_summary)
                    
                    if batch_summary.startswith("[Erreur"):
                        print(f"Erreur lors de la fusion du lot {i//batch_size + 1}: {batch_summary}")
                        batch_summary = f"[Résumé des sections {i+1} à {min(i+batch_size, len(batch_summaries))} non disponible]"
                    
                    intermediate_summaries.append(batch_summary)
                except Exception as e:
                    print(f"Erreur lors de la fusion du lot {i//batch_size + 1}: {str(e)}")
                    intermediate_summaries.append(f"[Erreur dans la fusion du lot {i//batch_size + 1}]")
            
            # Troisième étape: fusion finale des résumés intermédiaires
            summaries = intermediate_summaries
        else:
            # Stratégie standard pour les vidéos de taille normale
            for i, chunk in enumerate(chunks):
                try:
                    print(f"Résumé du chunk {i+1}/{len(chunks)} (taille: {len(chunk)} caractères)")
                    messages = [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": chunk}
                    ]
                    
                    # Obtenir le résumé pour ce chunk
                    chunk_summary = chat_with_lmstudio(messages)
                    
                    # Nettoyer immédiatement le résumé
                    chunk_summary = sanitize_markdown(chunk_summary)
                    
                    # Vérifier si le résumé contient une erreur
                    if chunk_summary.startswith("[Erreur"):
                        print(f"Erreur lors du résumé du chunk {i+1}: {chunk_summary}")
                        # En cas d'erreur, simplifier la demande pour ce chunk
                        simplified_messages = [
                            {"role": "system", "content": "Résume ce texte en français simplement sans formatage, en commençant par un titre suivi d'un tiret. Réponds uniquement en français."},
                            {"role": "user", "content": chunk[:max_chunk_size // 2]}  # Utiliser moitié moins de texte
                        ]
                        chunk_summary = chat_with_lmstudio(simplified_messages)
                        chunk_summary = sanitize_markdown(chunk_summary)
                        
                    # Si toujours en erreur, utiliser un résumé générique
                    if chunk_summary.startswith("[Erreur"):
                        chunk_summary = f"[Contenu du segment {i+1}]"
                    
                    summaries.append(chunk_summary)
                except Exception as e:
                    print(f"Erreur lors du traitement du chunk {i+1}: {str(e)}")
                    summaries.append(f"[Erreur dans le segment {i+1}: {str(e)}]")

        # S'il n'y a qu'un seul résumé, pas besoin de fusion
        if len(summaries) == 1:
            return sanitize_markdown(summaries[0])
            
        # S'il y a trop de résumés, les regrouper par petits groupes
        if len(summaries) > 5:
            print(f"Fusion de {len(summaries)} résumés en groupes...")
            grouped_summaries = []
            group_size = 3
            
            for i in range(0, len(summaries), group_size):
                group = summaries[i:i+group_size]
                fusion_message = [
                    {"role": "system", "content": "Fusionne ces résumés partiels en un seul résumé cohérent sans formatage, en commençant par un titre suivi d'un tiret."},
                    {"role": "user", "content": "\n\n".join(group)}
                ]
                group_summary = chat_with_lmstudio(fusion_message)
                group_summary = sanitize_markdown(group_summary)
                grouped_summaries.append(group_summary)
                
            summaries = grouped_summaries

        # Fusion finale des résumés
        print("Fusion finale des résumés...")
        fusion_prompt = (
            "Voici plusieurs résumés partiels d'une vidéo. "
            "Fusionne-les en un résumé cohérent en commençant par un titre accrocheur qui résume le sujet principal, suivi d'un tiret. "
            "Mets en avant les idées clés et les informations qui apportent le plus de valeur au lecteur. "
            "N'utilise pas de formatage comme des astérisques ou du markdown."
        )

        messages = [
            {"role": "system", "content": fusion_prompt},
            {"role": "user", "content": "\n\n".join(summaries)}
        ]
        final_summary = chat_with_lmstudio(messages)
        
        # Nettoyer une dernière fois le résumé final
        final_summary = sanitize_markdown(final_summary)
        
        # Si la fusion finale échoue, retourner la concaténation des résumés
        if final_summary.startswith("[Erreur"):
            print(f"Erreur lors de la fusion finale: {final_summary}")
            concatenated = "\n\n".join([f"Partie {i+1}:\n{summary}" for i, summary in enumerate(summaries)])
            final_summary = sanitize_markdown(concatenated)
        
        # Vérification finale : s'assurer que le résumé n'est pas vide
        if not final_summary or not final_summary.strip():
            print("⚠️ Résumé final vide, création d'un résumé de secours")
            final_summary = "Résumé de la vidéo - Le contenu a été traité mais le résumé détaillé n'a pas pu être généré correctement."
            
        return final_summary
    except Exception as e:
        error_msg = f"[Erreur lors de la génération du résumé] {str(e)}"
        print(error_msg)
        return error_msg

def ask_question_about_subtitles(subtitles, question):
    # Limiter la taille des sous-titres en utilisant la configuration adaptative
    max_subtitle_length = get_adaptive_chunk_size()
    
    if len(subtitles) > max_subtitle_length:
        # Tronquer les sous-titres si trop longs
        subtitles = subtitles[:max_subtitle_length] + "... [texte tronqué]"
        print(f"⚠️ Sous-titres tronqués à {max_subtitle_length} caractères pour éviter le dépassement de contexte")
    
    prompt = (
        f"Voici la transcription d'une vidéo YouTube :\n\n{subtitles}\n\n"
        f"Réponds à la question suivante de manière claire et utile : {question}"
    )
    messages = [
        {"role": "system", "content": "Tu es un assistant qui répond précisément à des questions sur une vidéo."},
        {"role": "user", "content": prompt}
    ]
    return chat_with_lmstudio(messages)

def sanitize_markdown(text):
    """
    Nettoie le texte pour éviter les erreurs de formatage Markdown dans Telegram.
    Supprime complètement les caractères spéciaux de Markdown au lieu de les échapper.
    Décode également les entités HTML communes.
    """
    if not text:
        return ""
    
    # Étape 1: Décoder les entités HTML courantes
    html_entities = {
        '&quot;': '"',
        '&apos;': "'",
        '&#39;': "'",
        '&lt;': '<',
        '&gt;': '>',
        '&amp;': '&',
        '&nbsp;': ' ',
        '&ndash;': '-',
        '&mdash;': '—',
        '&lsquo;': ''',
        '&rsquo;': ''',
        '&ldquo;': '"',
        '&rdquo;': '"',
        '&bull;': '•',
        '&hellip;': '...',
        '&trade;': '™',
        '&copy;': '©',
        '&reg;': '®',
    }
    
    # Appliquer le remplacement pour les entités HTML connues
    for entity, replacement in html_entities.items():
        text = text.replace(entity, replacement)
    
    # Rechercher et remplacer d'autres entités HTML numériques (comme &#123;)
    import re
    text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)
    
    # Étape 2: Nettoyer les caractères de formatage Markdown
    # 1. Supprimer les astérisques (formatage gras/italique)
    text = text.replace('**', '').replace('*', '')
    
    # 2. Supprimer les soulignements (formatage italique)
    text = text.replace('__', '').replace('_', ' ')
    
    # 3. Supprimer les caractères spéciaux qui peuvent être interprétés comme du Markdown
    text = text.replace('`', '').replace('~', '').replace('#', '')
    
    # 4. Remplacer les crochets et parenthèses utilisés pour les liens
    text = text.replace('[', '').replace(']', '')
    
    # 5. Nettoyer les caractères utilisés pour les listes et citations
    text = text.replace('>', ' ').replace('- ', '').replace('+ ', '')
    
    # 6. Nettoyer les autres caractères problématiques
    text = text.replace('|', ' ').replace('\\', '')
    
    # 7. Supprimer les doubles espaces créés par les remplacements
    while '  ' in text:
        text = text.replace('  ', ' ')
    
    # 8. Supprimer les répétitions bizarres que certains modèles peuvent générer
    repeated_patterns = [
        (r'(\w+)\1{2,}', r'\1'),  # Mots répétés plus de 2 fois consécutives
        (r'([.!?]){3,}', r'\1\1\1'),  # Plus de 3 ponctuations de suite
    ]
    
    for pattern, replacement in repeated_patterns:
        text = re.sub(pattern, replacement, text)
    
    return text

def clean_text_for_audio(text):
    """
    Nettoie le texte spécifiquement pour la synthèse vocale.
    Supprime les marqueurs de formatage et les caractères qui ne doivent pas être prononcés.
    """
    # Commencer par le nettoyage complet (Markdown + HTML)
    clean_text = sanitize_markdown(text)
    
    # Remplacer le tiret entre le titre et le contenu par une pause plus longue
    # Cette regex cherche un tiret précédé par un mot et suivi par un espace
    import re
    clean_text = re.sub(r'(\w+)\s+-\s+', r'\1. ', clean_text)
    
    # Nettoyer les éléments spécifiques à l'audio
    clean_text = clean_text.replace('(', ', ').replace(')', ', ')
    clean_text = clean_text.replace(':', ', ').replace(';', ', ')
    clean_text = clean_text.replace('/', ' ou ')
    
    # Améliorer la gestion des tirets
    # Remplacer les tirets en début de ligne (puces) par un point
    clean_text = re.sub(r'^\s*-\s+', '• ', clean_text, flags=re.MULTILINE)
    
    # Remplacer les tirets utilisés comme séparateurs de mots par "à" ou un espace selon le contexte
    # Pour des nombres ou dates (ex: 1-2, 2020-2021)
    clean_text = re.sub(r'(\d+)-(\d+)', r'\1 à \2', clean_text)
    
    # Pour les tirets entre des mots, utiliser un espace
    clean_text = re.sub(r'([a-zA-Z])-([a-zA-Z])', r'\1 \2', clean_text)
    
    # Remplacer les tirets restants par des pauses légères
    clean_text = clean_text.replace(' - ', '. ')
    clean_text = clean_text.replace('-', ' ')
    
    # Remplacer les URL par un texte plus simple
    url_pattern = r'https?://[^\s]+'
    clean_text = re.sub(url_pattern, 'lien vers le site', clean_text)
    
    # Remplacer certains symboles par leur prononciation
    clean_text = clean_text.replace('%', ' pourcent ')
    clean_text = clean_text.replace('&', ' et ')
    clean_text = clean_text.replace('=', ' égal ')
    clean_text = clean_text.replace('+', ' plus ')
    
    # Remplacer les chiffres ordinaux par leur forme prononcée
    ordinals = {
        '1er': 'premier',
        '2e': 'deuxième',
        '3e': 'troisième',
        '4e': 'quatrième',
        '5e': 'cinquième',
        '6e': 'sixième',
        '7e': 'septième',
        '8e': 'huitième',
        '9e': 'neuvième',
        '10e': 'dixième'
    }
    
    for ordinal, pronunciation in ordinals.items():
        clean_text = re.sub(r'\b' + ordinal + r'\b', pronunciation, clean_text)
    
    # Nettoyer les doubles espaces
    while '  ' in clean_text:
        clean_text = clean_text.replace('  ', ' ')
    
    # Ajouter des points entre les phrases pour améliorer la diction
    clean_text = re.sub(r'([.!?])\s+', r'\1 ', clean_text)
    
    return clean_text

def text_to_audio(text, filename="resume.mp3"):
    """
    Convertit le texte en fichier audio MP3.
    Nettoie le texte avant de le convertir pour éviter les problèmes de prononciation.
    """
    # Vérifier si le texte d'entrée est valide
    if not text or not text.strip():
        print("⚠️ Texte vide fourni à text_to_audio")
        raise ValueError("No text to send to TTS API")
    
    print(f"🔊 Conversion en audio du texte ({len(text)} caractères)")
    
    # Nettoyer le texte pour la synthèse vocale
    clean_text = clean_text_for_audio(text)
    
    # Vérifier si le texte nettoyé est encore valide
    if not clean_text or not clean_text.strip():
        print("⚠️ Texte vide après nettoyage pour l'audio")
        print(f"Texte original: {text[:200]}...")
        # Utiliser le texte original si le nettoyage a tout supprimé
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("No text to send to TTS API")
    
    print(f"🧹 Texte nettoyé pour l'audio ({len(clean_text)} caractères)")
    
    # Convertir en audio
    try:
        tts = gTTS(clean_text, lang='fr')
        tts.save(filename)
        print(f"✅ Audio sauvegardé dans {filename}")
        return filename
    except Exception as e:
        print(f"❌ Erreur lors de la conversion TTS: {e}")
        raise

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
                
                # Nettoyer complètement le résumé des marqueurs Markdown et autres caractères problématiques
                clean_summary = sanitize_markdown(summary)
                
                # Créer le fichier audio (text_to_audio nettoiera aussi le texte pour l'audio)
                audio_path = text_to_audio(summary, f"resume_{video_id}.mp3")
                
                # Pour chaque utilisateur abonné, envoyer le résumé
                for user_id in subscribed_users:
                    try:
                        channel_name = CHANNEL_SUBSCRIPTIONS[user_id][channel_id]
                        
                        # Envoi du message texte en gérant les messages longs
                        message = (
                            f"🆕 Nouvelle vidéo de {channel_name}\n\n"
                            f"📺 {video_title}\n"
                            f"🔗 {video_url}\n\n"
                            f"📝 Résumé :\n{clean_summary}"
                        )
                        
                        await send_long_message(
                            context.bot,
                            chat_id=user_id,
                            text=message
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

async def handle_yt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Traite un lien YouTube explicitement envoyé via commande /yt"""
    message_parts = update.message.text.split(" ", 1)
    
    if len(message_parts) < 2:
        await update.message.reply_text(
            "❗ Utilisation : `/yt [lien YouTube]`\n\n"
            "Exemple : `/yt https://youtube.com/watch?v=VIDEO_ID`"
        )
        return
    
    url = message_parts[1].strip()
    
    # Vérifier si c'est un lien YouTube valide
    if "youtube.com" not in url and "youtu.be" not in url:
        await update.message.reply_text(
            "❌ L'URL fournie n'est pas une URL YouTube valide."
        )
        return
    
    # On simule un message normal contenant uniquement l'URL
    update.message.text = url
    
    # On appelle le handler standard pour le traitement
    await handle_message(update, context)

async def handle_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    CHAT_ACTIVE[user_id] = True
    USER_CHAT_MODES.setdefault(user_id, "libre")
    
    if user_id not in CONVERSATION_HISTORY:
        CONVERSATION_HISTORY[user_id] = []
    
    await update.message.reply_text(
        f"💬 Mode chat activé - {CHAT_MODES[USER_CHAT_MODES[user_id]]}\n\n"
        "Vous pouvez maintenant discuter avec moi à propos de vidéos YouTube.\n"
        "Envoyez /chat_mode pour changer de mode de conversation.\n"
        "Envoyez /reset pour effacer l'historique de conversation.\n"
        "Envoyez n'importe quel message pour continuer la conversation."
    )

async def handle_chat_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Basculer entre les modes disponibles
    current_mode = USER_CHAT_MODES.get(user_id, "libre")
    new_mode = "guidé" if current_mode == "libre" else "libre"
    USER_CHAT_MODES[user_id] = new_mode
    
    await update.message.reply_text(
        f"🔄 Mode de conversation modifié\n\n"
        f"Nouveau mode : {CHAT_MODES[new_mode]}"
    )

async def handle_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    CONVERSATION_HISTORY[user_id] = []
    
    await update.message.reply_text(
        "🗑️ Historique de conversation effacé\n\n"
        "Votre conversation a été réinitialisée."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        message_text = update.message.text or ""
        
        # Obtenir l'ID du chat (salon) où le message a été envoyé
        chat_id = update.effective_chat.id
        
        # Obtenir l'ID du thread/topic si le message est dans un salon de discussion
        thread_id = update.message.message_thread_id if hasattr(update.message, 'message_thread_id') else None
        
        # Log pour le débogage
        chat_type = update.effective_chat.type
        chat_title = getattr(update.effective_chat, 'title', 'Chat privé')
        print(f"\nMessage reçu dans {chat_type} (ID: {chat_id}): {message_text[:50]}...")
        if thread_id:
            print(f"Message dans le salon/thread ID: {thread_id}")
        
        # Préparer les paramètres de réponse pour envoyer au bon endroit
        reply_params = {"chat_id": chat_id}
        if thread_id:
            reply_params["message_thread_id"] = thread_id
        
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
                    await context.bot.send_message(text=error, **reply_params)
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
            
            # Nettoyer la réponse des marqueurs Markdown
            clean_response = sanitize_markdown(response)
            
            # Ajouter la réponse à l'historique
            CONVERSATION_HISTORY[user_id].append({"role": "assistant", "content": clean_response})
            
            # Envoyer la réponse sans formater en Markdown, en gérant les messages longs
            await send_long_message(context.bot, text=clean_response, **reply_params)
            return
        
        # Comportement normal (non-chat) : traitement des liens YouTube
        # Rechercher tous les liens YouTube dans le message
        youtube_links = []
        words = message_text.split()
        
        for word in words:
            if "youtube.com" in word or "youtu.be" in word:
                if extract_video_id(word):
                    youtube_links.append(word)
        
        if not youtube_links:
            # Ne rien faire si aucun lien YouTube n'est trouvé
            return
        
        # Initialiser la structure de file d'attente pour ce chat s'il n'existe pas encore
        if chat_id not in YOUTUBE_QUEUE:
            YOUTUBE_QUEUE[chat_id] = {
                "queue": [],
                "processing": False,
                "thread_id": thread_id
            }
        else:
            # Mettre à jour l'ID du thread si nécessaire
            YOUTUBE_QUEUE[chat_id]["thread_id"] = thread_id
        
        # Ajouter les liens à la file d'attente
        for url in youtube_links:
            if url not in YOUTUBE_QUEUE[chat_id]["queue"]:
                YOUTUBE_QUEUE[chat_id]["queue"].append(url)
        
        # Informer l'utilisateur du nombre de liens ajoutés à la file d'attente
        if YOUTUBE_QUEUE[chat_id]["processing"]:
            await context.bot.send_message(
                text=f"✅ {len(youtube_links)} lien(s) ajouté(s) à la file d'attente. Traitement en cours...",
                **reply_params
            )
        else:
            await context.bot.send_message(
                text=f"✅ {len(youtube_links)} lien(s) à traiter...",
                **reply_params
            )
            # Démarrer le traitement si aucun n'est en cours
            await process_youtube_queue(chat_id, context)
            
    except Exception as e:
        print(f"Erreur lors du traitement du message: {str(e)}")
        try:
            await update.message.reply_text(f"❌ Erreur lors du traitement du message: {str(e)}")
        except:
            pass

async def process_youtube_queue(chat_id, context):
    """Traite la file d'attente des liens YouTube pour un chat spécifique"""
    if chat_id not in YOUTUBE_QUEUE or not YOUTUBE_QUEUE[chat_id]["queue"]:
        return
    
    # Marquer comme en cours de traitement
    YOUTUBE_QUEUE[chat_id]["processing"] = True
    thread_id = YOUTUBE_QUEUE[chat_id]["thread_id"]
    
    # Préparer les paramètres de réponse
    reply_params = {"chat_id": chat_id}
    if thread_id:
        reply_params["message_thread_id"] = thread_id
    
    # Récupérer le prochain lien à traiter
    url = YOUTUBE_QUEUE[chat_id]["queue"].pop(0)
    
    try:
        # Informer l'utilisateur
        if len(YOUTUBE_QUEUE[chat_id]["queue"]) > 0:
            await context.bot.send_message(
                text=f"🔄 Traitement du lien: {url}\n({len(YOUTUBE_QUEUE[chat_id]['queue'])} liens en attente)",
                **reply_params
            )
        else:
            await context.bot.send_message(
                text=f"🔄 Traitement du lien: {url}",
                **reply_params
            )
        
        # Récupérer les sous-titres
        subtitles, error = get_subtitles(url)
        if error:
            await context.bot.send_message(text=f"❌ Erreur pour {url}: {error}", **reply_params)
            
            # Passer au lien suivant s'il y en a
            YOUTUBE_QUEUE[chat_id]["processing"] = False
            await process_youtube_queue(chat_id, context)
            return
        
        # Générer le résumé
        summary = summarize(subtitles)
        
        # Double nettoyage pour garantir l'absence de caractères spéciaux
        clean_summary = sanitize_markdown(sanitize_markdown(summary))
        
        # Vérifier qu'il n'y a pas d'entités HTML non décodées
        if '&' in clean_summary and (';' in clean_summary):
            # Log du problème
            print(f"Attention: Possible entité HTML non décodée dans le résumé")
            # Nettoyage agressif - supprimer les séquences problématiques
            import re
            clean_summary = re.sub(r'&[#\w]+;', '', clean_summary)
        
        # Envoyer le résumé texte
        message_text = f"📝 Résumé de {url} :\n\n{clean_summary}"
        await send_long_message(context.bot, text=message_text, **reply_params)
        
        # Attendre un peu pour éviter de submerger l'API Telegram
        await asyncio.sleep(4)
        
        # Créer et envoyer l'audio
        try:
            audio_path = text_to_audio(summary, f"resume_queue.mp3")
            
            try:
                with open(audio_path, 'rb') as audio_file:
                    if thread_id:
                        await context.bot.send_voice(
                            chat_id=chat_id,
                            message_thread_id=thread_id,
                            voice=audio_file,
                            caption=f"🎙️ Résumé audio"
                        )
                    else:
                        await context.bot.send_voice(
                            chat_id=chat_id,
                            voice=audio_file,
                            caption=f"🎙️ Résumé audio"
                        )
            except Exception as e:
                await context.bot.send_message(
                    text=f"⚠️ Erreur lors de l'envoi de l'audio: {str(e)}",
                    **reply_params
                )
            finally:
                # Supprimer le fichier audio
                if os.path.exists(audio_path):
                    os.remove(audio_path)
                    
        except ValueError as ve:
            if "No text to send to TTS API" in str(ve):
                print(f"⚠️ Résumé vide pour l'audio, pas de fichier audio généré pour {url}")
                await context.bot.send_message(
                    text="⚠️ Le résumé textuel a été généré mais la conversion audio n'a pas pu être effectuée (contenu vide après nettoyage).",
                    **reply_params
                )
            else:
                raise ve
        except Exception as e:
            print(f"❌ Erreur lors de la création de l'audio: {str(e)}")
            await context.bot.send_message(
                text=f"⚠️ Erreur lors de la création de l'audio: {str(e)}",
                **reply_params
            )
    
    except Exception as e:
        # En cas d'erreur, informer l'utilisateur
        print(f"Erreur lors du traitement de {url}: {str(e)}")
        await context.bot.send_message(
            text=f"❌ Erreur lors du traitement de {url}: {str(e)}",
            **reply_params
        )
    
    # Marquer comme terminé et passer au lien suivant s'il y en a
    YOUTUBE_QUEUE[chat_id]["processing"] = False
    await process_youtube_queue(chat_id, context)

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    message_parts = message_text.split(" ", 1)
    
    if len(message_parts) < 2:
        await update.message.reply_text(
            "❗ Utilisation : `/question [lien YouTube] [votre question]`\n\n"
            "Exemple : `/question https://youtube.com/watch?v=VIDEO_ID Quelle est la conclusion principale ?`"
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
            "Veuillez inclure un lien YouTube dans votre requête."
        )
        return
    
    question = " ".join(question_words).strip()
    
    if not question:
        await update.message.reply_text(
            "❓ Vous n'avez pas posé de question. Que souhaitez-vous savoir sur cette vidéo?"
        )
        return
    
    # Afficher un message d'attente
    processing_message = await update.message.reply_text(
        "⏳ Je récupère les sous-titres et analyse la vidéo..."
    )
    
    # Récupérer les sous-titres
    subtitles, error = get_subtitles(url)
    if error:
        await processing_message.edit_text(
            f"❌ {error}"
        )
        return
    
    await processing_message.edit_text(
        "⏳ J'analyse la vidéo et prépare une réponse à votre question..."
    )
    
    # Répondre à la question
    answer = ask_question_about_subtitles(subtitles, question)
    
    # Nettoyer la réponse pour éviter les problèmes de formatage
    clean_answer = sanitize_markdown(answer)
    
    try:
        # Supprimer le message d'attente
        await processing_message.delete()
        # Envoyer la réponse en gérant les longs messages
        full_message = f"Question : {question}\n\n{clean_answer}"
        await send_long_message(context.bot, chat_id=update.effective_chat.id, text=full_message)
    except Exception as e:
        print(f"Erreur lors de l'envoi de la réponse: {str(e)}")
        # En cas d'erreur, supprimer le message d'attente
        try:
            await processing_message.delete()
        except:
            pass
        # Envoyer un message d'erreur
        await update.message.reply_text(f"❌ Erreur lors de l'envoi de la réponse: {str(e)}")

async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🤖 Bot YouTube Telegram 🤖

Ce bot vous permet d'interagir avec des vidéos YouTube de façon intelligente.

📋 Commandes disponibles :

• /start - Démarrer le bot
• /help ou /h - Afficher ce message d'aide

Résumé et questions :
• Envoyez un lien YouTube pour obtenir un résumé
• /yt - Traiter explicitement un lien YouTube
• /question ou /q - Poser une question sur une vidéo

Mode conversation :
• /chat ou /c - Activer le mode conversation
• /mode - Changer le mode conversation (libre/guidé)
• /reset ou /r - Effacer l'historique de conversation

Abonnements :
• /subscribe ou /sub - S'abonner à une chaîne
• /unsubscribe ou /unsub - Se désabonner
• /list ou /subs - Voir vos abonnements

📝 Exemples :
1. Résumé : envoyez simplement un lien YouTube
2. Question : /q https://youtube.com/watch?v=VIDEO_ID Quelle est la conclusion ?
3. Abonnement : /sub https://www.youtube.com/@NomDeLaChaine

📢 Utilisation dans les groupes :
• Mentionnez le bot avec @nomdubot avant ou après le lien YouTube
• Utilisez /yt pour traiter directement un lien
• Répondez à un message du bot avec un lien YouTube
"""
    await update.message.reply_text(help_text)

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
👋 Bienvenue sur le Bot YouTube Telegram !

Ce bot vous aide à obtenir des résumés et à poser des questions sur des vidéos YouTube grâce à l'intelligence artificielle.

🔍 Pour commencer :
• Envoyez simplement un lien YouTube pour obtenir un résumé
• Utilisez /help pour voir toutes les commandes disponibles

Bonne utilisation ! 🚀
"""
    await update.message.reply_text(welcome_text)

async def handle_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_parts = update.message.text.split(" ", 1)
    
    if len(message_parts) < 2:
        await update.message.reply_text(
            "❗ Utilisation : /subscribe [URL chaîne YouTube]\n\n"
            "Exemple : /subscribe https://www.youtube.com/@NomDeLaChaine"
        )
        return
    
    channel_url = message_parts[1].strip()
    
    # Vérifier si c'est une URL YouTube valide
    if "youtube.com" not in channel_url and "youtu.be" not in channel_url:
        await update.message.reply_text(
            "❌ L'URL fournie n'est pas une URL YouTube valide.\n\n"
            "Exemple d'URL valide : https://www.youtube.com/@NomDeLaChaine"
        )
        return
    
    # Obtenir les informations de la chaîne
    channel_info = get_channel_info(channel_url)
    
    if not channel_info:
        await update.message.reply_text(
            "❌ Impossible d'obtenir les informations de cette chaîne.\n\n"
            "Assurez-vous que l'URL est correcte."
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
            f"ℹ️ Vous êtes déjà abonné à la chaîne {channel_name}."
        )
        return
    
    CHANNEL_SUBSCRIPTIONS[user_id][channel_id] = channel_name
    
    # Initialiser le suivi des dernières vidéos pour cette chaîne
    if channel_id not in LATEST_VIDEOS:
        LATEST_VIDEOS[channel_id] = []
    
    # Sauvegarder les abonnements
    save_subscriptions()
    
    await update.message.reply_text(
        f"✅ Vous êtes maintenant abonné à la chaîne {channel_name}.\n\n"
        "Vous recevrez des résumés des nouvelles vidéos publiées sur cette chaîne."
    )

async def handle_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_parts = update.message.text.split(" ", 1)
    
    if user_id not in CHANNEL_SUBSCRIPTIONS or not CHANNEL_SUBSCRIPTIONS[user_id]:
        await update.message.reply_text(
            "❗ Vous n'êtes abonné à aucune chaîne YouTube."
        )
        return
    
    if len(message_parts) < 2:
        # Liste les chaînes auxquelles l'utilisateur est abonné
        channels_list = "\n".join([f"• {name} - /unsubscribe {channel_id}" 
                                 for channel_id, name in CHANNEL_SUBSCRIPTIONS[user_id].items()])
        
        await update.message.reply_text(
            "❗ Utilisation : /unsubscribe [ID chaîne YouTube]\n\n"
            "Vos abonnements actuels :\n"
            f"{channels_list}\n\n"
            "Choisissez l'ID de la chaîne dont vous souhaitez vous désabonner."
        )
        return
    
    channel_id_or_url = message_parts[1].strip()
    
    # Vérifie si c'est une URL ou un ID
    if "youtube.com" in channel_id_or_url or "youtu.be" in channel_id_or_url:
        channel_info = get_channel_info(channel_id_or_url)
        if not channel_info:
            await update.message.reply_text(
                "❌ Impossible d'obtenir les informations de cette chaîne.\n\n"
                "Assurez-vous que l'URL est correcte."
            )
            return
        channel_id = channel_info["id"]
    else:
        channel_id = channel_id_or_url
    
    # Vérifie si l'utilisateur est abonné à cette chaîne
    if channel_id not in CHANNEL_SUBSCRIPTIONS[user_id]:
        await update.message.reply_text(
            "❌ Vous n'êtes pas abonné à cette chaîne."
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
        f"✅ Vous êtes maintenant désabonné de la chaîne {channel_name}."
    )

async def handle_list_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in CHANNEL_SUBSCRIPTIONS or not CHANNEL_SUBSCRIPTIONS[user_id]:
        await update.message.reply_text(
            "ℹ️ Vous n'êtes abonné à aucune chaîne YouTube."
        )
        return
    
    channels_list = "\n".join([f"• {name} ({channel_id})" 
                             for channel_id, name in CHANNEL_SUBSCRIPTIONS[user_id].items()])
    
    await update.message.reply_text(
        "📋 Vos abonnements actuels :\n\n"
        f"{channels_list}\n\n"
        "Pour vous désabonner d'une chaîne, utilisez :\n"
        "/unsubscribe [ID chaîne]"
    )

def split_message_for_telegram(text, max_length=4000):
    """
    Divise un message en plusieurs parties pour respecter la limite de taille de Telegram.
    
    Args:
        text (str): Le texte à diviser
        max_length (int): Longueur maximale d'un message (4096 est le max pour Telegram, on utilise 4000 par sécurité)
        
    Returns:
        list: Liste des parties du message
    """
    if not text:
        return [""]
        
    if len(text) <= max_length:
        return [text]
        
    parts = []
    current_part = ""
    
    # Diviser en paragraphes pour essayer de préserver la structure du texte
    paragraphs = text.split('\n\n')
    
    for paragraph in paragraphs:
        # Si ce paragraphe ferait dépasser la limite
        if len(current_part) + len(paragraph) + 2 > max_length:
            # Si le paragraphe lui-même est trop long
            if len(paragraph) > max_length:
                # Si la partie courante n'est pas vide, on l'ajoute
                if current_part:
                    parts.append(current_part)
                    current_part = ""
                
                # On divise le paragraphe en morceaux
                words = paragraph.split(' ')
                for word in words:
                    if len(current_part) + len(word) + 1 > max_length:
                        parts.append(current_part)
                        current_part = word
                    else:
                        if current_part:
                            current_part += " " + word
                        else:
                            current_part = word
            else:
                # On ajoute la partie courante et on commence une nouvelle
                parts.append(current_part)
                current_part = paragraph
        else:
            # On ajoute le paragraphe à la partie courante
            if current_part:
                current_part += "\n\n" + paragraph
            else:
                current_part = paragraph
    
    # Ajouter la dernière partie si elle n'est pas vide
    if current_part:
        parts.append(current_part)
    
    return parts

async def send_long_message(bot, text, **kwargs):
    """
    Envoie un message potentiellement long en le divisant si nécessaire.
    Gère les timeouts et ajoute des délais entre les messages pour éviter les erreurs Telegram.
    
    Args:
        bot: L'instance du bot Telegram
        text: Le texte du message
        **kwargs: Arguments supplémentaires pour send_message (comme chat_id, message_thread_id)
        
    Returns:
        Le dernier message envoyé
    """
    if not text:
        return None
        
    # S'assurer que chat_id est dans les kwargs
    if 'chat_id' not in kwargs:
        print("Erreur: chat_id manquant dans send_long_message")
        return None
        
    # Diviser le message si nécessaire
    message_parts = split_message_for_telegram(text)
    
    last_message = None
    
    # Envoyer chaque partie avec délai entre les envois
    for i, part in enumerate(message_parts):
        # Ajouter un indicateur de partie pour les messages divisés
        if len(message_parts) > 1:
            part_indicator = f"[Partie {i+1}/{len(message_parts)}]\n\n"
            part = part_indicator + part
            
        # Essayer d'envoyer avec gestion avancée des erreurs
        max_retries = 5  # Augmenté de 3 à 5 tentatives
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Attendre un peu entre les messages (délai proportionnel à la longueur du message)
                if i > 0:
                    # Attendre entre 2 et 5 secondes selon la longueur du message (augmenté)
                    wait_time = min(2 + (len(part) / 1500), 5)
                    await asyncio.sleep(wait_time)
                    
                # Envoyer le message avec tous les paramètres fournis
                last_message = await bot.send_message(text=part, **kwargs)
                break  # Sortir de la boucle si l'envoi a réussi
                
            except telegram.error.TimedOut:
                retry_count += 1
                print(f"Timeout lors de l'envoi de la partie {i+1}/{len(message_parts)}. Tentative {retry_count}/{max_retries}...")
                
                if retry_count >= max_retries:
                    # Si on a atteint le nombre maximum de tentatives
                    print(f"Échec après {max_retries} tentatives pour la partie {i+1}.")
                    
                    # Essayer d'envoyer un message plus court
                    try:
                        error_msg = f"[Une partie du message n'a pas pu être envoyée en raison d'un timeout. Partie {i+1}/{len(message_parts)}]"
                        last_message = await bot.send_message(text=error_msg, **kwargs)
                    except:
                        pass
                else:
                    # Attendre avant de réessayer (délai de plus en plus long, augmenté)
                    await asyncio.sleep(3 * retry_count)
                    
            except Exception as e:
                print(f"Erreur lors de l'envoi de la partie {i+1}: {e}")
                
                # Essayer avec un message plus simple
                try:
                    error_msg = f"[Impossible d'afficher une partie du message. Erreur: {str(e)}]"
                    last_message = await bot.send_message(text=error_msg, **kwargs)
                except:
                    pass
                    
                break  # Passer à la partie suivante
                
    return last_message

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
        
    if not config_ok:
        print("\n⚠️ Le bot peut ne pas fonctionner correctement en raison de problèmes de configuration.")
        print("Veuillez vérifier le fichier .env et vous assurer que toutes les variables sont correctement définies.")
        exit(1)
    else:
        print("✅ Configuration OK")
    
    print("=== Fin de la vérification de configuration ===\n")
    
    # Test de connexion à LM Studio
    print("=== Test de connexion à LM Studio ===")
    max_retries = 3
    retry_count = 0
    lm_available = False
    
    while retry_count < max_retries and not lm_available:
        if retry_count > 0:
            print(f"Tentative {retry_count+1}/{max_retries}...")
            time.sleep(3)  # Attendre avant de réessayer
            
        lm_available = check_lmstudio_availability()
        retry_count += 1
    
    if not lm_available:
        print("\n⚠️ ATTENTION: Impossible de se connecter à LM Studio après plusieurs tentatives.")
        print("Le bot va démarrer, mais les fonctionnalités liées à LM Studio ne fonctionneront pas correctement.")
        print("Veuillez vérifier que:")
        print("1. LM Studio est bien lancé sur votre ordinateur")
        print("2. L'API REST est activée dans les options de LM Studio") 
        print("3. L'URL dans votre fichier .env correspond à l'URL affichée dans LM Studio")
        print("4. Un modèle est bien chargé dans LM Studio")
        print("\nAppuyez sur Ctrl+C pour arrêter le bot, ou attendez pour démarrer sans LM Studio...\n")
        time.sleep(5)
    else:
        print("=== Fin du test de connexion ===\n")
    
    # Charger les abonnements existants
    load_subscriptions()
    
    # Créer l'application avec une configuration simplifiée et protection contre les conflits
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Note: Le nettoyage des webhooks se fera automatiquement au démarrage du polling
    
    # Afficher un message pour confirmer le bon démarrage
    print("\n=== DÉMARRAGE DU BOT ===")
    print(f"Token: {TELEGRAM_TOKEN[:5]}...{TELEGRAM_TOKEN[-5:]}")
    
    # Handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Handler principal
    app.add_handler(CommandHandler("question", handle_question))
    app.add_handler(CommandHandler("q", handle_question))  # Alias court pour question
    
    # Commande pour traiter directement un lien YouTube
    app.add_handler(CommandHandler("yt", handle_yt))
    
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
    print("🚀 Bot démarré ! Utilisez Ctrl+C pour arrêter.")
    
    # Attendre quelques secondes pour éviter les conflits avec d'anciennes instances
    print("⏳ Attente de 3 secondes pour éviter les conflits...")
    time.sleep(3)
    
    # Activer tous les types de mises à jour pour une meilleure compatibilité
    try:
        print("🔄 Démarrage du polling...")
        app.run_polling(allowed_updates=telegram.Update.ALL_TYPES)
    except telegram.error.Conflict as e:
        print(f"❌ Conflit détecté: {e}")
        print("⏳ Attente de 10 secondes pour résoudre le conflit...")
        time.sleep(10)
        print("🔄 Nouvelle tentative de démarrage...")
        app.run_polling(allowed_updates=telegram.Update.ALL_TYPES)
