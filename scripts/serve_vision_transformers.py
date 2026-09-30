#!/usr/bin/env python
"""Minimal fallback UI-TARS server (no vLLM).

Only needed if vLLM cannot serve ``ByteDance-Seed/UI-TARS-2B-SFT``. Exposes an
OpenAI-compatible subset using the standard library HTTP server plus
``transformers``:

    GET  /v1/models
    POST /v1/chat/completions

Run it on GPU 1:

    CUDA_VISIBLE_DEVICES=1 .venv/bin/python scripts/serve_vision_transformers.py \
        --model models/UI-TARS-2B-SFT --served-model-name uitars --port 8000

Flags mirror scripts/serve_vision.sh. Add ``--trust-remote-code`` if a future
UI-TARS build ships custom modeling code.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_LOCK = threading.Lock()
_STATE: dict = {"model": None, "processor": None, "served_name": "uitars", "torch": None}


def _extract_image(content_part):
    """Return a PIL.Image from a data URL image_url content part."""
    from PIL import Image  # type: ignore

    url = content_part.get("image_url", {}).get("url", "") or ""
    if url.startswith("data:"):
        _, _, b64 = url.partition(",")
    else:
        b64 = url
    raw = base64.b64decode(b64)
    return Image.open(io.BytesIO(raw)).convert("RGB")


def _build_inputs(messages: list[dict]):
    """Convert OpenAI messages into (prompt_text, [PIL images])."""
    images = []
    normalized = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            normalized.append({"role": msg["role"], "content": [{"type": "text", "text": content}]})
            continue
        parts = []
        for part in content or []:
            if part.get("type") == "image_url":
                images.append(_extract_image(part))
                parts.append({"type": "image", "image": ""})
            else:
                parts.append({"type": "text", "text": part.get("text", "")})
        normalized.append({"role": msg["role"], "content": parts})
    return normalized, images


def _generate(body: dict) -> dict:
    import torch  # type: ignore

    model = _STATE["model"]
    processor = _STATE["processor"]
    messages, images = _build_inputs(body.get("messages", []))

    prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    if images:
        inputs = processor(text=[prompt], images=images, return_tensors="pt", padding=True)
    else:
        inputs = processor(text=[prompt], return_tensors="pt", padding=True)
    inputs = {k: v.to(model.device) for k, v in inputs.items()}

    max_tokens = int(body.get("max_tokens") or 128)
    temperature = float(body.get("temperature") or 0.0)
    gen_kwargs: dict[str, Any] = {"max_new_tokens": max_tokens}
    if temperature > 0:
        gen_kwargs.update({"do_sample": True, "temperature": temperature})
    else:
        gen_kwargs.update({"do_sample": False})

    with torch.inference_mode():
        out = model.generate(**inputs, **gen_kwargs)
    trimmed = out[:, inputs["input_ids"].shape[1]:]
    text = processor.batch_decode(trimmed, skip_special_tokens=True)[0].strip()

    return {
        "id": f"chatcmpl-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": _STATE["served_name"],
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002 - matches stdlib signature
        print(f"[serve_vision_transformers] {format % args}", flush=True)

    def _send_json(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": _STATE["served_name"], "object": "model", "owned_by": "local"}
                    ],
                },
            )
        else:
            self._send_json(404, {"error": {"message": f"unknown path {self.path}"}})

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            self._send_json(404, {"error": {"message": f"unknown path {self.path}"}})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": {"message": f"bad json: {exc}"}})
            return
        try:
            with _LOCK:
                result = _generate(body)
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"error": {"message": f"{type(exc).__name__}: {exc}"}})
            return
        self._send_json(200, result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="models/UI-TARS-2B-SFT")
    parser.add_argument("--served-model-name", default="uitars")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--trust-remote-code", action="store_true")
    args = parser.parse_args()

    import torch  # type: ignore
    from transformers import AutoProcessor, Qwen2VLForConditionalGeneration  # type: ignore

    print(f"[serve_vision_transformers] loading {args.model} ({args.dtype})", flush=True)
    processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=args.trust_remote_code)
    model = Qwen2VLForConditionalGeneration.from_pretrained(
        args.model,
        torch_dtype=getattr(torch, args.dtype),
        device_map="auto",
        trust_remote_code=args.trust_remote_code,
    )
    model.eval()

    _STATE.update(
        {"model": model, "processor": processor, "served_name": args.served_model_name, "torch": torch}
    )

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        f"[serve_vision_transformers] listening on http://{args.host}:{args.port}/v1 "
        f"(model={args.served_model_name})",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
