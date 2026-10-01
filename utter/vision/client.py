"""HTTP client for the local UI-TARS grounding server.

The inference lane serves ``ByteDance-Seed/UI-TARS-2B-SFT`` (Qwen2-VL arch)
behind vLLM's OpenAI-compatible endpoint on ``http://127.0.0.1:8000/v1``.
This client is HTTP-only and dependency-light: ``requests`` is imported lazily
and PIL is optional (used only to resize the screenshot before upload).

Grounding convention (UI-TARS-1.0 / 2B-SFT):
    * coordinates are normalized to ``0..1000``
    * the model emits e.g.
      ``Action: click(start_box='<|box_start|>(512,345)<|box_end|>')``
``ground`` scales those into native screen pixels using ``screen_w``/``screen_h``.
"""
from __future__ import annotations

import base64
import io
import os
import re
import time
from typing import Any

from utter.types import Point

# Qwen2-VL patch/merge geometry: image sides should be multiples of 28.
_PATCH_MULTIPLE = 28
_DEFAULT_TARGET_WIDTH = 1344
_DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
_DEFAULT_MODEL = "uitars"

# Canonical UI-TARS action-space prompt. Coordinates are 0-1000 normalized.
GROUNDING_PROMPT = """You are a GUI agent. You are given a task and a screenshot. \
You need to output the next action to complete the task.

## Output Format
```
Action: ...
```

## Action Space

click(start_box='<|box_start|>(x1,y1)<|box_end|>')
left_double(start_box='<|box_start|>(x1,y1)<|box_end|>')
right_single(start_box='<|box_start|>(x1,y1)<|box_end|>')
drag(start_box='<|box_start|>(x1,y1)<|box_end|>', end_box='<|box_start|>(x2,y2)<|box_end|>')
hotkey(key='')
type(content='')
scroll(start_box='<|box_start|>(x1,y1)<|box_end|>', direction='down')
wait()
finished()
answer(content='')

## Note
- Use normalized coordinates in the range 0-1000 for start_box.
- To click an element, use: Action: click(start_box='<|box_start|>(x,y)<|box_end|>')

## User Instruction
{instruction}"""


def _cfg():
    try:
        from utter.config import load_config

        return load_config().vision
    except Exception:  # noqa: BLE001 - config is optional for a pure client
        return None


def _base_url() -> str:
    env = os.environ.get("UTTER_VISION_URL")
    if env:
        return env.rstrip("/")
    from utter import runtime
    cfg = _cfg()
    resolved = runtime.resolve_vision(cfg)
    base = getattr(resolved, "base_url", None) or _DEFAULT_BASE_URL
    return base.rstrip("/")


def _model() -> str:
    env = os.environ.get("UTTER_VISION_MODEL")
    if env:
        return env
    from utter import runtime
    cfg = _cfg()
    resolved = runtime.resolve_vision(cfg)
    return getattr(resolved, "model", None) or _DEFAULT_MODEL


def _target_width() -> int:
    env = os.environ.get("UTTER_VISION_TARGET_WIDTH")
    if env:
        return int(env)
    cfg = _cfg()
    return int(getattr(cfg, "target_width", None) or _DEFAULT_TARGET_WIDTH)


def _timeout() -> float:
    return float(os.environ.get("UTTER_VISION_TIMEOUT", "60"))


def _round_to_multiple(value: int, multiple: int = _PATCH_MULTIPLE) -> int:
    return max(multiple, int(round(value / multiple)) * multiple)


def _load_pil():
    try:
        from PIL import Image  # type: ignore

        return Image
    except Exception:  # noqa: BLE001
        return None


def prepare_image(image_path: str, target_width: int | None = None) -> bytes:
    """Return PNG bytes resized to ``target_width`` wide (the latency lever).

    Preserves aspect ratio and snaps the height to a multiple of 28 for
    Qwen2-VL. If PIL is unavailable the original file bytes are returned
    unchanged.
    """
    target_width = target_width or _target_width()
    Image = _load_pil()
    if Image is None:
        with open(image_path, "rb") as fh:
            return fh.read()
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        if w <= 0 or h <= 0:
            raise ValueError(f"bad image size {w}x{h}")
        new_w = _round_to_multiple(target_width)
        new_h = _round_to_multiple(round(h * (new_w / w)))
        if (new_w, new_h) != (w, h):
            im = im.resize((new_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()


_BOX_RE = re.compile(
    r"<\|box_start\|>\s*\(?\s*([0-9]+(?:\.[0-9]+)?)\s*[,\s]\s*([0-9]+(?:\.[0-9]+)?)\s*\)?\s*<\|box_end\|>"
)
_POINT_RE = re.compile(
    r"<point>\s*([0-9]+(?:\.[0-9]+)?)\s*[,\s]\s*([0-9]+(?:\.[0-9]+)?)\s*</point>"
)
_PAREN_RE = re.compile(
    r"\(\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*\)"
)


def _to_pixels(nx: float, ny: float, screen_w: int, screen_h: int) -> Point:
    x = int(round(nx / 1000.0 * screen_w))
    y = int(round(ny / 1000.0 * screen_h))
    x = max(0, min(screen_w - 1, x))
    y = max(0, min(screen_h - 1, y))
    return Point(x, y)


def parse_points(text: str, screen_w: int, screen_h: int) -> list[Point]:
    """Parse normalized 0-1000 coordinates out of a UI-TARS response."""
    matches: list[tuple[float, float]] = []
    for match in _BOX_RE.findall(text or ""):
        matches.append((float(match[0]), float(match[1])))
    if not matches:
        for match in _POINT_RE.findall(text or ""):
            matches.append((float(match[0]), float(match[1])))
    if not matches:
        for match in _PAREN_RE.findall(text or ""):
            matches.append((float(match[0]), float(match[1])))
    return [_to_pixels(nx, ny, screen_w, screen_h) for nx, ny in matches]


def is_up(timeout: float = 1.5) -> bool:
    """True if the vLLM UI-TARS server answers ``GET /v1/models``."""
    try:
        import requests

        resp = requests.get(f"{_base_url()}/models", timeout=timeout)
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def ground(
    image_path: str,
    instruction: str,
    screen_w: int,
    screen_h: int,
    *,
    target_width: int | None = None,
    max_tokens: int = 128,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Ground ``instruction`` in ``image_path`` and return native pixels.

    Returns a dict::

        {
            "points": [Point, ...] | None,
            "raw": str,            # raw model text
            "latency_ms": float,
            "status": int,         # HTTP status (0 on transport error)
        }

    ``points`` are absolute pixel coordinates in the screenshot's own frame
    (scale ``screen_w``/``screen_h``); callers add the capture Rect origin if
    the screenshot came from an offset monitor.
    """
    import requests

    start = time.perf_counter()
    png = prepare_image(image_path, target_width)
    b64 = base64.b64encode(png).decode("ascii")
    prompt = GROUNDING_PROMPT.format(instruction=instruction)

    payload = {
        "model": _model(),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }

    status = 0
    raw = ""
    points: list[Point] | None = None
    try:
        resp = requests.post(
            f"{_base_url()}/chat/completions",
            json=payload,
            timeout=timeout or _timeout(),
        )
        status = resp.status_code
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"].get("content") or ""
        points = parse_points(raw, screen_w, screen_h) or None
    except Exception as exc:  # noqa: BLE001 - report as raw error, never raise
        raw = f"{type(exc).__name__}: {exc}"

    latency_ms = (time.perf_counter() - start) * 1000.0
    return {"points": points, "raw": raw, "latency_ms": latency_ms, "status": status}
