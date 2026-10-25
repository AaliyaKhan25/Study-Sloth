# Deploying Study Sloth on Render

The Render Blueprint in `render.yaml` creates two web services:

| Service | App | Plan |
| --- | --- | --- |
| `study-sloth-online` | Notes/PDF study tools (`online.py`) | Free |
| `study-sloth-hosted` | Full hosted Study Sloth workspace (`web.py`), including CPU-based audio/video transcription | Standard + 5 GB persistent disk |

The full hosted service needs the Standard instance for CPU-based Whisper transcription and a persistent disk for its SQLite workspaces, uploads, and cached transcription model. Render's Standard service and disk are billable; check the current price in your Render dashboard before deploying. The free lightweight online service may sleep when idle and its in-progress jobs/results are held in memory.

## Create the services

1. Push this repository to a Git provider supported by Render.
2. In Render, create a **Blueprint** from the repository and review the two services and their plans before applying it.
3. For **both** services, set `OLLAMA_API_KEY` in the Render dashboard to a valid Ollama Cloud API key. It is a secret: do not put it in this repository. The Blueprint sets `OLLAMA_HOST` to `https://ollama.com` and `SLOTH_MODEL` to `gemma3:4b`. Confirm Gemma 3 4B is available to your Ollama Cloud account.
4. Wait for both deploys to finish, then check each service URL. AI requests require a valid key and model access.

The hosted app is the full browser-workspace version, including audio/video transcription. Whisper runs on the Render server using CPU; the first transcription may take longer while the model is downloaded and cached on the persistent disk. Its workspace data, uploads, and model cache are stored on that disk, but there is no account login; do not upload sensitive or confidential material. Processing runs on your Render service rather than on the student's device.

## Connect the .tech domain

After the services are live, open each service's **Settings → Custom Domains** in Render and add the domain names:

- `studysloth.tech` for `study-sloth-hosted` (full app)
- `quick.studysloth.tech` for `study-sloth-online` (lightweight notes/PDF experience)

At the company where the domain's DNS is managed, add the records exactly as Render displays them. DNS controls may be at the registrar or a separate DNS provider. Then return to Render and verify the domains. Do not guess the record values: they are specific to the domain and service.
