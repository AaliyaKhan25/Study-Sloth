# Deploying Study Sloth on Render

The Render Blueprint in `render.yaml` creates two web services:

| Service | App | Plan |
| --- | --- | --- |
| `study-sloth-online` | Notes/PDF study tools (`online.py`) | Free |
| `study-sloth-hosted` | Hosted Study Sloth workspace (`web.py`) | Starter + 1 GB persistent disk |

The hosted service needs a persistent disk to retain its SQLite workspaces and uploads. Render's Starter service and disk are billable; check the current price in your Render dashboard before deploying. The free online service may sleep when idle and its in-progress jobs/results are held in memory.

## Create the services

1. Push this repository to a Git provider supported by Render.
2. In Render, create a **Blueprint** from the repository and review the two services and their plans before applying it.
3. For **both** services, set `OLLAMA_API_KEY` in the Render dashboard to a valid Ollama Cloud API key. It is a secret: do not put it in this repository. The Blueprint sets `OLLAMA_HOST` to `https://ollama.com`.
4. Wait for both deploys to finish, then check each service URL. AI requests require a valid key and model access.

The hosted app is an online, browser-workspace version: audio/video transcription is intentionally available only in the local app. Its workspace data is persisted on the Render disk, but there is no account login; do not upload sensitive or confidential material.

## Connect the .tech domain

After the services are live, open each service's **Settings → Custom Domains** in Render and add the domain names:

- `studysloth.tech` for `study-sloth-online`
- `app.studysloth.tech` for `study-sloth-hosted`

At the company where the domain's DNS is managed, add the records exactly as Render displays them. DNS controls may be at the registrar or a separate DNS provider. Then return to Render and verify the domains. Do not guess the record values: they are specific to the domain and service.
