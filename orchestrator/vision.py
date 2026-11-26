"""Give a controller without image input a way to delegate looking at one (issue #26).

Two rules from the rest of the repo are enforced here, not just documented:

* capability is data — a model serves vision only if the policy says `vision: true`, and that flag is
  set only where it was verified against the live upstream;
* no silent downgrade — with no vision model available the caller gets `no_vision_model`, never a
  text-only model pretending it looked.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import urllib.request

MIME_BY_SUFFIX = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".webp": "image/webp", ".gif": "image/gif"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
DEFAULT_GATEWAY = "http://127.0.0.1:8787"


def mime_for(path: pathlib.Path) -> str | None:
    return MIME_BY_SUFFIX.get(path.suffix.lower())


def read_image(path: str | pathlib.Path) -> tuple[str, str]:
    """Return (mime, base64) or raise ValueError with a reason the caller can act on."""
    p = pathlib.Path(path)
    mime = mime_for(p)
    if mime is None:
        raise ValueError(f"unsupported image type '{p.suffix}' (png/jpg/webp/gif only)")
    if not p.exists():
        raise ValueError(f"image not found at {p}")
    raw = p.read_bytes()
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f"image is {len(raw)} bytes, over the {MAX_IMAGE_BYTES} cap")
    return mime, base64.b64encode(raw).decode("ascii")


def build_content(question: str, images: list[tuple[str, str]]) -> list[dict]:
    """OpenAI-style content blocks: the question first, then one image_url block per attachment."""
    blocks: list[dict] = [{"type": "text", "text": question}]
    for mime, b64 in images:
        blocks.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    return blocks


def vision_model_for(catalog: dict[str, dict], requested: str | None = None) -> str | None:
    """Pick a model the policy declares vision-capable; `requested` wins when it qualifies."""
    if requested and (catalog.get(requested) or {}).get("vision"):
        return requested
    for key, cfg in catalog.items():
        if cfg.get("vision"):
            return key
    return None


def analyze_image(question: str, paths: list[str], *, model: str | None = None,
                  catalog: dict[str, dict] | None = None, gateway: str | None = None,
                  timeout: float = 120.0) -> dict:
    """Send the images to a vision-capable model and return its answer plus which model saw them."""
    catalog = catalog if catalog is not None else {}
    chosen = vision_model_for(catalog, model)
    if chosen is None:
        return {"ok": False, "error": "no_vision_model",
                "message": "no model in the policy declares vision: true; set it on a verified model first"}
    images: list[tuple[str, str]] = []
    for path in paths:
        try:
            images.append(read_image(path))
        except ValueError as exc:
            return {"ok": False, "error": "image_unreadable", "message": str(exc), "path": str(path)}
    if not images:
        return {"ok": False, "error": "no_attachments", "message": "analyze_image needs at least one path"}
    payload = {"model": chosen, "stream": False, "max_tokens": 800,
               "messages": [{"role": "user", "content": build_content(question, images)}]}
    req = urllib.request.Request(f"{(gateway or os.getenv('HARNESS_GATEWAY_URL') or DEFAULT_GATEWAY).rstrip('/')}/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json",
                                          "X-Harness-No-Contract": "1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            served = resp.headers.get("x-harness-selected-model") or chosen
            body = json.loads(resp.read())
    except OSError as exc:
        return {"ok": False, "error": "gateway_unreachable", "message": str(exc)}
    content = ((body.get("choices") or [{}])[0].get("message") or {}).get("content")
    return {"ok": True, "model": served, "requested_model": chosen,
            "images": len(images), "answer": content}
