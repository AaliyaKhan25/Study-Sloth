# Deploying Study Sloth on Render

The Render Blueprint in `render.yaml` creates two web services:

| Service | App | Plan |
| --- | --- | --- |
| `study-sloth-online` | Notes/PDF study tools (`online.py`) | Free |
| `study-sloth-hosted` | Full hosted Study Sloth workspace (`web.py`), including Groq API audio/video transcription | Free |

Both services use Render's free web-service plan. The full app sends audio/video recordings to Groq's speech-to-text API instead of running a Whisper model on Render. Free Render services have an ephemeral filesystem: workspaces, SQLite data, and uploads may be lost after a restart, redeploy, or sleep cycle. Free services can sleep when idle. Check Groq's current API limits, file-size restrictions, and pricing before use.

## Create the full app as a Web Service

1. Push this repository to GitHub and create a **Web Service** in Render from `AaliyaKhan25/Study-Sloth`, branch `main`.
2. Set **Root Directory** to blank and choose the **Free** instance type.
3. Use these commands:

   ```text
   Build:  pip install -r requirements-web.txt
   Start:  uvicorn web:app --host 0.0.0.0 --port $PORT
   ```

4. Add the environment variables below. Mark both API keys as secrets. Do not commit or share them.

   | Key | Value |
   | --- | --- |
   | `PYTHON_VERSION` | `3.12.11` |
   | `OLLAMA_HOST` | `https://ollama.com` |
   | `OLLAMA_API_KEY` | Your Ollama Cloud API key (secret) |
   | `SLOTH_MODEL` | `gemma3:4b` |
   | `SLOTH_VISION_MODEL` | `qwen3-vl:4b-instruct` |
   | `GROQ_API_KEY` | Your Groq API key (secret) |
   | `GROQ_TRANSCRIPTION_MODEL` | `whisper-large-v3-turbo` |

   Confirm the selected models and current usage limits are available to your accounts.
5. Do **not** add a disk or set the old `/var/data` values for `SLOTH_DB`, `SLOTH_UPLOAD_DIR`, or `HF_HOME` on this free service. The app uses default writable filesystem paths, which are temporary on Render Free.
6. Deploy and check the service URL. AI and transcription requests require valid provider keys and available quotas.

The `render.yaml` Blueprint is also configured for free services, but you can create the web service manually with the settings above instead.

The hosted app includes browser-based audio/video transcription via Groq. Recordings are sent to Groq for processing; the direct upload limit is 25 MB. Review Groq's data-handling terms and current quota/pricing before uploading. Render's free filesystem is temporary, so the app's SQLite workspace data and uploads are not durable and can disappear during service restarts or redeploys. The app does not have account login; do not upload sensitive or confidential material.

If you previously added `/var/data` environment paths while configuring a persistent disk, remove `SLOTH_DB`, `SLOTH_UPLOAD_DIR`, and `HF_HOME` from the free service. The app detects an unmounted `/var/data` path and falls back to temporary storage with a warning, but removing those variables keeps the setup clear.

## Connect the .tech domain

After the services are live, open each service's **Settings → Custom Domains** in Render and add the domain names:

- `studysloth.tech` for `study-sloth-hosted` (full app)
- `quick.studysloth.tech` for `study-sloth-online` (lightweight notes/PDF experience)

At the company where the domain's DNS is managed, add the records exactly as Render displays them. DNS controls may be at the registrar or a separate DNS provider. Then return to Render and verify the domains. Do not guess the record values: they are specific to the domain and service.
