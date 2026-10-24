import httpx, json, base64, os
HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("SLOTH_MODEL", "qwen3:4b")             # text, Apache-2.0
VISION = os.environ.get("SLOTH_VISION_MODEL", "qwen3-vl:4b-instruct")  # board photos and screenshots, Apache-2.0

def chat(prompt, system="", images=None, json_mode=False, num_predict=None):
    msg = {"role": "user", "content": prompt}
    if images: msg["images"] = [base64.b64encode(i).decode() for i in images]
    body = {"model": VISION if images else MODEL, "stream": False, "think": False,
            "messages": [{"role": "system", "content": system}, msg],
            "options": {"temperature": 0.2, "num_ctx": 8192}}
    if num_predict is not None: body["options"]["num_predict"] = num_predict
    if json_mode: body["format"] = "json"
    r = httpx.post(f"{HOST}/api/chat", json=body, timeout=900)
    r.raise_for_status()
    return r.json()["message"]["content"]

def chat_json(prompt, **kw):
    for _ in range(2):
        try:
            d = json.loads(chat(prompt, json_mode=True, **kw))
            if isinstance(d, dict): return d
        except Exception: pass
    return {}
