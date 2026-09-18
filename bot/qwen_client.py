import base64
import json
import re

from openai import OpenAI

import config


class QwenError(RuntimeError):
    pass


_client = None


def client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.QWEN_API_KEY, base_url=config.QWEN_BASE_URL, timeout=config.QWEN_TIMEOUT, max_retries=1)
    return _client


def _image_data_uri(path):
    raw = path.read_bytes()
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))


def _create(kwargs):
    completion = client().chat.completions.create(**kwargs)
    choice = completion.choices[0]
    if choice.finish_reason == "length":
        raise QwenError("balasan terpotong karena batas token")
    return (choice.message.content or "").strip()


def _thinking_body(thinking):
    if not thinking:
        return {"enable_thinking": False}
    body = {"enable_thinking": True}
    if isinstance(thinking, int) and not isinstance(thinking, bool):
        body["thinking_budget"] = thinking
    return body


def _attempt(kwargs):
    try:
        return _create(kwargs)
    except Exception as exc:
        detail = str(exc)
        if "response_format" in detail and "response_format" in kwargs:
            kwargs.pop("response_format")
            return _attempt(kwargs)
        if "thinking" in detail.lower() and "extra_body" in kwargs:
            kwargs.pop("extra_body")
            return _attempt(kwargs)
        raise


def chat(messages, models=None, temperature=0.6, max_tokens=2400, json_mode=False, thinking=False):
    candidates = models or config.QWEN_TEXT_MODELS
    errors = []
    budget = thinking if isinstance(thinking, int) and not isinstance(thinking, bool) else 0
    for name in candidates:
        kwargs = {
            "model": name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens + budget,
            "extra_body": _thinking_body(thinking),
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            content = _attempt(kwargs)
            if content:
                return content, name
            errors.append("%s: kosong" % name)
        except Exception as exc:
            errors.append("%s: %s" % (name, str(exc)[:220]))
    raise QwenError(" | ".join(errors))


def chat_json(system_prompt, user_prompt, models=None, temperature=0.3, max_tokens=2400, thinking=False):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last = None
    for attempt in range(2):
        raw, used = chat(messages, models=models, temperature=temperature, max_tokens=max_tokens, json_mode=True, thinking=thinking)
        try:
            return parse_json(raw), used
        except QwenError as exc:
            last = exc
    raise last


def parse_json(raw):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*", "", text).strip("` \n")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise QwenError("balasan Qwen bukan JSON valid: " + text[:200])


def vision(prompt, image_paths, models=None, temperature=0.3, json_mode=False, max_tokens=2400):
    parts = [{"type": "text", "text": prompt}]
    for path in image_paths:
        parts.append({"type": "image_url", "image_url": {"url": _image_data_uri(path)}})
    return vision_parts(parts, models=models, temperature=temperature, json_mode=json_mode, max_tokens=max_tokens)


def vision_parts(parts, models=None, temperature=0.3, json_mode=False, max_tokens=2400, system_prompt=None):
    content = []
    for part in parts:
        if isinstance(part, str):
            content.append({"type": "text", "text": part})
        elif isinstance(part, dict) and "image" in part:
            content.append({"type": "image_url", "image_url": {"url": _image_data_uri(part["image"])}})
        else:
            content.append(part)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": content})
    return chat(messages, models=models or config.QWEN_VL_MODELS, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)


def text_models():
    return list(config.QWEN_TEXT_MODELS)


def fast_models():
    return list(config.QWEN_FAST_MODELS)


def vision_models():
    return list(config.QWEN_VL_MODELS)
