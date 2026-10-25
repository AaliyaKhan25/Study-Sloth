import httpx, json, base64, os, re
HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")   # https://ollama.com for Ollama Cloud
KEY = os.environ.get("OLLAMA_API_KEY", "")                                    # only needed for Ollama Cloud
MODEL = os.environ.get("SLOTH_MODEL", "qwen3:4b")
VISION = os.environ.get("SLOTH_VISION_MODEL", "qwen3-vl:4b-instruct")

def _clean(t):
    return re.sub(r"<think>.*?</think>", "", t, flags=re.S).strip()

def chat(prompt, system="", images=None, json_mode=False, **opts):
    """Extra keyword arguments (num_predict, temperature, num_ctx, ...) are passed to the model as options."""
    think = opts.pop("think", False)
    model = opts.pop("model", None)
    timeout = opts.pop("timeout", 900)
    options = {"temperature": 0.2, "num_ctx": 8192}
    options.update({k: v for k, v in opts.items() if v is not None})
    msg = {"role": "user", "content": prompt}
    if images: msg["images"] = [base64.b64encode(i).decode() for i in images]
    body = {"model": model or (VISION if images else MODEL), "stream": False, "think": think,
            "messages": [{"role": "system", "content": system}, msg], "options": options}
    if json_mode: body["format"] = "json"
    headers = {"Authorization": f"Bearer {KEY}"} if KEY else {}
    r = httpx.post(f"{HOST}/api/chat", json=body, headers=headers, timeout=timeout)
    if r.status_code == 400 and "think" in r.text.lower():     # this model does not accept the think option
        body.pop("think")
        r = httpx.post(f"{HOST}/api/chat", json=body, headers=headers, timeout=timeout)
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