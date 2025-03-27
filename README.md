# Telegram Bot + LM Studio

Ce bot Telegram :

- Reçoit un lien YouTube
- Récupère les sous-titres (auto/traduits en français)
- Résume le contenu avec ton modèle local via **LM Studio**
- Envoie le résumé écrit et audio (voix)
- Répond à des questions avec la commande `/question`

## ✅ Configuration

1. Assure-toi que LM Studio est lancé avec l'API locale activée :
   - Va dans `Settings > Enable local server`
   - Par défaut : `http://localhost:1234`

2. Utilise un modèle comme `DeepSeek R1 Distill Qwen 7B`.

3. Copie `.env.example` en `.env` et remplis avec ton token Telegram.

## 🚀 Lancer le bot

```bash
pip install -r requirements.txt
python bot.py
```

## 💬 Utilisation

- Envoyer un lien YouTube → résumé automatique
- Poser une question :
```
/question https://youtu.be/abc123defg ? Quelle est l’idée principale ?
```