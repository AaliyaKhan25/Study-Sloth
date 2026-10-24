import httpx, json, base64, os, re
HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("SLOTH_MODEL", "qwen3:4b")
VISION = os.environ.get("SLOTH_VISION_MODEL", "qwen3-vl:4b-instruct")
BACKEND = os.environ.get("SLOTH_BACKEND", "ollama")   # "ollama" = fully local (default); "digitalocean" = hosted open model
DO_URL = "https://inference.do-ai.run/v1/chat/completions"
DO_KEY = os.environ.get("DO_MODEL_ACCESS_KEY", "")
DO_MODEL = os.environ.get("DO_MODEL", "")

def _clean(t):
    return re.sub(r"<think>.*?</think>", "", t, flags=re.S).strip()

def chat(prompt, system="", images=None, json_mode=False):
    if BACKEND == "digitalocean" and not images:      # images always stay on your own machine
        r = httpx.post(DO_URL, headers={"Authorization": f"Bearer {DO_KEY}"}, timeout=300,
                       json={"model": DO_MODEL, "temperature": 0.2,
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
        r.raise_for_status()
        return _clean(r.json()["choices"][0]["message"]["content"])
    msg = {"role": "user", "content": prompt}
    if images: msg["images"] = [base64.b64encode(i).decode() for i in images]
    body = {"model": VISION if images else MODEL, "stream": False, "think": False,
            "messages": [{"role": "system", "content": system}, msg],
            "options": {"temperature": 0.2, "num_ctx": 8192}}
    if json_mode: body["format"] = "json"
    r = httpx.post(f"{HOST}/api/chat", json=body, timeout=900)
    r.raise_for_status()
    return _clean(r.json()["message"]["content"])

def chat_json(prompt, **kw):
    for _ in range(2):
        try:
            t = chat(prompt, json_mode=True, **kw)
            m = re.search(r"\{.*\}", t, re.S)
            d = json.loads(m.group(0) if m else t)
            if isinstance(d, dict): return d
        except ValueError:          # bad JSON: retry once. Network/auth errors are NOT hidden.
            pass
    return {}