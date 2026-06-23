# ElevenLabs → Telegram Webhook Relay

A tiny Flask app that receives ElevenLabs post-call webhooks, checks whether
the `whatsapp_requested` data-collection field is `true`, and if so sends a
formatted message to a Telegram group. Calls where it's `false` are silently
acknowledged — nothing is sent.

This is meant to run for free on Render (or any similar free web service
host) so you're not limited by Make.com's monthly operation quota.

---

## 1. Create a Telegram bot (skip if you already have one)

1. Open Telegram, search for **@BotFather**, start a chat
2. Send `/newbot`, follow the prompts, get your **bot token**
   (looks like `123456789:ABCdefGHIjklMNOpqrSTUvwxYZ`)
3. Add the bot to your target group, then find your **chat ID**:
   - Easiest way: send any message in the group, then visit
     `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
     and look for `"chat":{"id": -100...}` in the response

## 2. Push this code to GitHub

1. Create a new **public or private** GitHub repo (e.g. `elevenlabs-telegram-webhook`)
2. Upload these files: `app.py`, `requirements.txt`, this `README.md`
   (you can drag-and-drop them in GitHub's web UI — no git command line needed)

## 3. Deploy on Render (free tier)

1. Go to https://render.com and sign up (free, no credit card needed for this tier)
2. Click **New +** → **Web Service**
3. Connect your GitHub account and select the repo you just created
4. Configure:
   - **Name:** anything, e.g. `elevenlabs-telegram-webhook`
   - **Region:** closest to you
   - **Branch:** `main`
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Instance Type:** Free
5. Under **Environment Variables**, add:
   - `TELEGRAM_BOT_TOKEN` = your bot token
   - `TELEGRAM_CHAT_ID` = your group chat ID (including the minus sign if present)
6. Click **Create Web Service**

Render will build and deploy automatically. Once live, you'll get a public
URL like:

```
https://elevenlabs-telegram-webhook.onrender.com
```

Your webhook endpoint is that URL + `/webhook/elevenlabs`, e.g.:

```
https://elevenlabs-telegram-webhook.onrender.com/webhook/elevenlabs
```

## 4. Point ElevenLabs at this URL

In ElevenLabs, set your post-call webhook URL to the address above
(the one ending in `/webhook/elevenlabs`).

## 5. Test it

1. Make a test call where you clearly ask for the WhatsApp number
2. Check Render's **Logs** tab for your service — you should see a line like
   `Processed call conv_... — whatsapp_requested=True`
3. Check your Telegram group for the message

## Notes on the free tier

- Render's free web services "spin down" after ~15 minutes of no traffic and
  take a few seconds to wake up on the next request. This is fine here —
  ElevenLabs will just wait briefly for the response, and post-call webhooks
  aren't time-critical.
- There is no per-call cost or operation limit on this approach — it scales
  to any call volume for $0.
- If you ever want to filter on additional fields (e.g. also alert when
  `human_followup_needed` is true), edit the `if whatsapp_requested is True:`
  line in `app.py` to add the extra condition, then push the change to GitHub
  — Render redeploys automatically.

## Security note (optional, recommended later)

This basic version doesn't verify that incoming webhook requests are
genuinely from ElevenLabs. ElevenLabs supports HMAC signature verification
via the `ElevenLabs-Signature` header — worth adding once you're past the
testing phase to prevent spoofed requests from triggering Telegram spam.
