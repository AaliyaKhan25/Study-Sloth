import mimetypes
import os

import httpx

MAX_FILE_BYTES = 25_000_000
TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def transcribe(path, progress):
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Hosted lecture transcription is not configured. Set the GROQ_API_KEY environment variable.")

    file_size = os.path.getsize(path)
    if file_size > MAX_FILE_BYTES:
        raise RuntimeError("This recording exceeds Groq's 25 MB upload limit. Compress or shorten it, then try again.")

    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    progress(0.05, "Uploading lecture for transcription")
    with open(path, "rb") as audio:
        response = httpx.post(
            TRANSCRIPTION_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            data={
                "model": os.environ.get("GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3-turbo"),
                "response_format": "verbose_json",
                "timestamp_granularities[]": "segment",
            },
            files={"file": (os.path.basename(path), audio, content_type)},
            timeout=600,
        )

    if response.status_code in (401, 403):
        raise RuntimeError("Groq rejected the transcription API key. Check the GROQ_API_KEY Render secret.")
    if response.status_code == 413:
        raise RuntimeError("This recording exceeds Groq's upload limit. Compress or shorten it, then try again.")
    if response.status_code == 429:
        raise RuntimeError("Groq's transcription quota or rate limit was reached. Check your Groq account and try again later.")
    response.raise_for_status()

    result = response.json()
    segments = result.get("segments") or []
    lines = [
        f"[{int(float(segment.get('start', 0)) // 60):02d}:{int(float(segment.get('start', 0)) % 60):02d}] "
        f"{str(segment.get('text', '')).strip()}"
        for segment in segments
        if isinstance(segment, dict) and str(segment.get("text", "")).strip()
    ]
    if not lines:
        text = str(result.get("text", "")).strip()
        if text:
            lines = [text]
    if not lines:
        raise RuntimeError("Groq returned no speech in the transcription. Check that the recording contains audible speech.")

    progress(0.5, "Transcription complete")
    return lines
