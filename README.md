<div align="center">

# Study Sloth

### Turn study material into a study plan you can actually use.

Study Sloth is an AI-assisted study workspace that transforms notes, syllabi, lectures, and lab work into organized learning materials—so students can spend less time formatting and more time understanding.

[Features](#what-you-can-do) · [Get started](#run-locally) · [AI models](#ai-models) · [Deployment](#deployment) · [Contributing](#contributing)

</div>

---

## Why Study Sloth?

Studying often means jumping between lecture files, notes, flashcards, quizzes, code, and lab-record templates. Study Sloth brings those tasks together in one calm, student-focused interface. Add your material and build a useful next step from it: clearer notes, revision questions, or a structured lab record.

The project has three ways to use it:

| Experience | Best for | Entry point |
| --- | --- | --- |
| **Local Study Sloth** | A personal workspace, including video/audio lecture transcription and lab tools | `app.main:app` |
| **Hosted Study Sloth** | A browser-based workspace hosted on Render | `web:app` |
| **Study Sloth Online** | A lightweight notes-and-PDF study-material generator | `online:app` |

The hosted and online experiences have different capabilities from the local app. See [What you can do](#what-you-can-do) before choosing an entry point.

## What you can do

### Organize a course

- Create subjects and add a syllabus as text or a file.
- Turn syllabus content into units and topics.
- Keep course material and study resources grouped by subject.

### Learn from notes and lectures

- Upload text-based PDFs and generate structured notes.
- Process lecture audio or video locally into a transcript and study notes.
- Use board images as supporting lecture material.
- Generate revision content such as flashcards, quizzes, and viva questions.

### Build and study lab work

- Review lab code and actual run output together.
- Generate a lab manual from an experiment list and student/course details.
- Include generated expected output in the manual, or provide your own actual output.
- Create flashcards and quizzes associated with a generated manual.
- Print a lab record or save it as a PDF from the browser.

> **A note about AI-generated material:** Review generated notes, expected outputs, and explanations before relying on them. For assessed lab work, verify results by running the experiment yourself and follow your institution's requirements.

### Know which version supports what

| Capability | Local app | Hosted Study Sloth | Study Sloth Online |
| --- | :---: | :---: | :---: |
| Course organization and syllabus | Yes | Yes | — |
| PDF notes | Yes | Yes | Yes |
| Lecture audio/video transcription | Yes (local Whisper) | Yes (Groq API; 25 MB upload limit) | — |
| Lab records and generated lab manuals | Yes | Yes | — |
| Study cards and quizzes | Yes | Yes | Yes |
| Per-browser hosted workspace | — | Yes | — |

The hosted variants use Ollama Cloud for study-content generation. Hosted audio/video recordings are sent to Groq for transcription (up to 25 MB per upload). Review each provider's data-handling terms before uploading; avoid confidential material.

## Interface

Study Sloth uses a light, high-contrast visual theme with forest-green accents, warm highlights, and Poppins typography. The interface is designed to make course material and action states easy to scan across the study workflow.

## Run locally

### Requirements

- Python 3.12 recommended
- Git
- [Ollama](https://ollama.com/) for local model inference, or an Ollama Cloud API key
- For local audio/video lecture transcription: the dependencies in the root `requirements.txt` (including the compatible PyAV range)

### 1. Get the project

```powershell
git clone https://github.com/AaliyaKhan25/Study-Sloth.git
cd Study-Sloth
```

### 2. Create an environment and install dependencies

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks environment activation, run the project interpreter directly instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Choose a model provider

For a local Ollama model, install Ollama, download the model you want to use, and keep the default local endpoint:

```powershell
ollama pull gemma3:4b
$env:OLLAMA_HOST = "http://localhost:11434"
$env:SLOTH_MODEL = "gemma3:4b"
```

To use Ollama Cloud instead, set the cloud endpoint and API key in the current PowerShell session. Never commit the key or paste it into source files:

```powershell
$env:OLLAMA_HOST = "https://ollama.com"
$env:OLLAMA_API_KEY = "<your Ollama Cloud API key>"
```

### 4. Start the local app

```powershell
python -m uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Local data is written under `data/` by default. The database and uploads are excluded from Git.

## AI models

Study Sloth uses the Ollama chat API and lets you select the text and vision models through environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama-compatible API endpoint |
| `OLLAMA_API_KEY` | Empty | API key for a hosted Ollama provider |
| `SLOTH_MODEL` | `gemma3:4b` | Text-generation model |
| `SLOTH_VISION_MODEL` | `qwen3-vl:4b-instruct` | Model used when an image is included |
| `SLOTH_WHISPER` | `small` | Local faster-whisper model size |
| `GROQ_API_KEY` | Empty | Secret API key for hosted audio/video transcription |
| `GROQ_TRANSCRIPTION_MODEL` | `whisper-large-v3-turbo` | Groq speech-to-text model |

**Gemma:** Study Sloth uses Gemma 3 4B (`gemma3:4b`) as its default text-generation model, including in the Render Blueprint. For a local run:

```powershell
ollama pull gemma3:4b
$env:SLOTH_MODEL = "gemma3:4b"
```

The vision model has its own setting, `SLOTH_VISION_MODEL`, and remains Qwen 3 VL by default. For a Gemma-focused deployment, set `SLOTH_MODEL=gemma3:4b` on the Render service. Confirm your Ollama Cloud account provides access to this model before deployment.

GitHub Copilot was used as an AI development assistant during implementation. It is not required to run Study Sloth.

## Deployment

The repository includes a [Render Blueprint](./render.yaml) for two free web services:

| Render service | Application | Deployment notes |
| --- | --- | --- |
| `study-sloth-online` | `online.py` | Free plan; lightweight notes/PDF workflow |
| `study-sloth-hosted` | `web.py` | Free plan; Groq API transcription |

The deployment configuration is prepared for Render and the `.tech` domain `studysloth.tech`:

- `studysloth.tech` is intended for the complete Study Sloth workspace.
- `quick.studysloth.tech` is intended for the lightweight notes/PDF experience.

The domain and Render configuration are **not proof that the services have been deployed or DNS has been connected**. A Render account, valid `OLLAMA_API_KEY` and (for the full hosted app) `GROQ_API_KEY` configured as secrets, service deployment, and DNS changes at the domain's DNS provider are still required. Render supplies the exact DNS records after custom domains are added. Free Render services have ephemeral storage; SQLite data and uploaded files may be lost after restarts or redeploys. Check Groq's current API quota and pricing.

For a manual Render Web Service (without a Blueprint), use:

```text
Build:  pip install -r requirements-web.txt
Start:  uvicorn web:app --host 0.0.0.0 --port $PORT
```

Leave **Root Directory** blank. Set `OLLAMA_HOST=https://ollama.com`, `OLLAMA_API_KEY` (secret), `SLOTH_MODEL=gemma3:4b`, `SLOTH_VISION_MODEL=qwen3-vl:4b-instruct`, `GROQ_API_KEY` (secret), and `GROQ_TRANSCRIPTION_MODEL=whisper-large-v3-turbo`. Do not set the old `/var/data` paths (`SLOTH_DB`, `SLOTH_UPLOAD_DIR`, or `HF_HOME`) on a free service without a disk.

For the step-by-step checklist, see [DEPLOYMENT.md](./DEPLOYMENT.md).

### Start a hosted entry point locally

Install the web dependencies:

```powershell
python -m pip install -r requirements-web.txt
```

Then run one entry point:

```powershell
# Hosted Study Sloth workspace
python -m uvicorn web:app --host 0.0.0.0 --port 8000

# Or, in a separate run, the lightweight online study site
python -m uvicorn online:app --host 0.0.0.0 --port 8000
```

Set `OLLAMA_HOST` and `OLLAMA_API_KEY` as appropriate before starting. To use hosted audio/video transcription, set `GROQ_API_KEY`; the default model is `whisper-large-v3-turbo`, and direct uploads are limited to 25 MB. Study Sloth Online stores active jobs and results in memory, so they are temporary and may not survive a service restart.

## Configuration and privacy

- `SLOTH_DB` selects the SQLite database path.
- `SLOTH_UPLOAD_DIR` selects the upload directory for the full app.
- `OLLAMA_HOST` and `OLLAMA_API_KEY` configure the model API endpoint.
- `SLOTH_MODEL` and `SLOTH_VISION_MODEL` select the text and image models.
- `SLOTH_WHISPER` selects the local faster-whisper model size.
- `GROQ_API_KEY` and `GROQ_TRANSCRIPTION_MODEL` configure hosted audio/video transcription.

The hosted workspace separates browser workspaces using a browser cookie; it does **not** provide user accounts or a sign-in system. Do not treat it as an authenticated private vault. For a public deployment, configure quotas and operational monitoring, secure provider credentials, and publish a privacy notice that matches your actual hosting and model-provider setup.

## Project structure

```text
Study-Sloth/
├── app/
│   ├── main.py                 # Local application API and routes
│   ├── pipeline.py             # Study-material processing workflows
│   ├── hosted_transcription.py # Groq speech-to-text integration
│   ├── llm.py                  # Ollama-compatible model client
│   ├── db.py                   # SQLite schema and database helpers
│   └── static/                 # Local application interface and logo
├── online/
│   └── index.html              # Lightweight online study interface
├── online.py                  # Online notes/PDF study service
├── web.py                     # Hosted full-workspace entry point
├── requirements.txt           # Full/local app dependencies
├── requirements-web.txt       # Hosted web dependencies
├── render.yaml                # Render Blueprint for both services
├── DEPLOYMENT.md              # Render and .tech domain checklist
└── tests/
    └── test_smoke.py           # Workflow smoke tests
```

## Run tests

With the project environment active:

```powershell
python -m pytest -q
```

The smoke tests exercise core study flows, including lab-manual output and study-card behavior.

## Contributing

Contributions are welcome. A good contribution keeps the workflows clear, handles failures visibly, protects user content, and includes tests for behavior changes.

1. Fork the repository and create a focused branch.
2. Set up the project by following [Run locally](#run-locally).
3. Make a small, well-scoped change and add or update tests.
4. Run `python -m pytest -q` and `git diff --check`.
5. Open a pull request describing the user-facing change and how it was verified.

## Acknowledgments

- **GitHub Copilot** — AI-assisted software development.
- **Gemma 3 4B** — the default text-generation model, served through Ollama.
- **Ollama** — local and hosted model API integration.
- **Render** — deployment target configured for the hosted services.
- **`.tech`** — the project domain selected for the planned public presence: `studysloth.tech`.

---

<div align="center">

**Study smarter. Stay curious. Let the Sloth handle the busywork.**

</div>
