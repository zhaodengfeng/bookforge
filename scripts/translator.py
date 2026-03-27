#!/usr/bin/env python3
"""Unified translation interface supporting DeepL, OpenAI, Google Gemini, and Claude."""

import os
import sys
import json
import re
from abc import ABC, abstractmethod


class TranslationEngine(ABC):
    """Base class for translation engines."""

    @abstractmethod
    def translate(self, text: str, target_lang: str, source_lang: str = "auto") -> str:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass


class DeepLEngine(TranslationEngine):
    """DeepL API translation engine. Free tier: 500k chars/month."""

    LANG_MAP = {
        "zh": "ZH", "en": "EN-US", "ja": "JA", "ko": "KO",
        "fr": "FR", "de": "DE", "es": "ES", "pt": "PT-BR",
        "ru": "RU", "it": "IT", "nl": "NL", "pl": "PL",
    }

    def __init__(self):
        self.api_key = os.environ.get("DEEPL_API_KEY", "")
        if not self.api_key:
            raise ValueError("DEEPL_API_KEY environment variable not set")
        self.base_url = "https://api-free.deepl.com" if ":fx" in self.api_key else "https://api.deepl.com"

    @property
    def name(self) -> str:
        return "DeepL"

    def translate(self, text: str, target_lang: str, source_lang: str = "auto") -> str:
        import urllib.request
        import urllib.parse

        target = self.LANG_MAP.get(target_lang.lower(), target_lang.upper())
        data = urllib.parse.urlencode({
            "text": text,
            "target_lang": target,
        }).encode()

        req = urllib.request.Request(
            f"{self.base_url}/v2/translate",
            data=data,
            headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
        return result["translations"][0]["text"]


class OpenAIEngine(TranslationEngine):
    """OpenAI GPT-4o-mini translation engine."""

    def __init__(self, model: str = "gpt-4o-mini"):
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        self.model = model

    @property
    def name(self) -> str:
        return f"OpenAI ({self.model})"

    def translate(self, text: str, target_lang: str, source_lang: str = "auto") -> str:
        import urllib.request

        lang_name = get_lang_name(target_lang)
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": f"You are a professional translator. Translate the following text to {lang_name}. Preserve all markdown formatting, code blocks, and special characters. Only output the translated text, nothing else."},
                {"role": "user", "content": text},
            ],
            "temperature": 0.3,
        }).encode()

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
        return result["choices"][0]["message"]["content"]


class GeminiEngine(TranslationEngine):
    """Google Gemini translation engine."""

    def __init__(self, model: str = "gemini-2.0-flash"):
        self.api_key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set")
        self.model = model

    @property
    def name(self) -> str:
        return f"Gemini ({self.model})"

    def translate(self, text: str, target_lang: str, source_lang: str = "auto") -> str:
        import urllib.request

        lang_name = get_lang_name(target_lang)
        payload = json.dumps({
            "contents": [{
                "parts": [{"text": f"You are a professional translator. Translate the following text to {lang_name}. Preserve all markdown formatting, code blocks, and special characters. Only output the translated text, nothing else.\n\n{text}"}]
            }],
            "generationConfig": {"temperature": 0.3},
        }).encode()

        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
        return result["candidates"][0]["content"]["parts"][0]["text"]


class ClaudeEngine(TranslationEngine):
    """Anthropic Claude translation engine."""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        self.model = model

    @property
    def name(self) -> str:
        return f"Claude ({self.model})"

    def translate(self, text: str, target_lang: str, source_lang: str = "auto") -> str:
        import urllib.request

        lang_name = get_lang_name(target_lang)
        payload = json.dumps({
            "model": self.model,
            "max_tokens": 8192,
            "messages": [
                {"role": "user", "content": f"You are a professional translator. Translate the following text to {lang_name}. Preserve all markdown formatting, code blocks, and special characters. Only output the translated text, nothing else.\n\n{text}"},
            ],
            "temperature": 0.3,
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
        return result["content"][0]["text"]


class OpenRouterEngine(TranslationEngine):
    """OpenRouter API — access hundreds of models through one API.

    Popular models for translation:
    - google/gemini-2.0-flash-001 (cheap, fast)
    - anthropic/claude-sonnet-4 (high quality)
    - openai/gpt-4o-mini (balanced)
    - deepseek/deepseek-chat-v3-0324 (cheap, good for CJK)
    - qwen/qwen-2.5-72b-instruct (good for Chinese)
    """

    def __init__(self, model: str = "google/gemini-2.0-flash-001"):
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable not set")
        self.model = model

    @property
    def name(self) -> str:
        return f"OpenRouter ({self.model})"

    def translate(self, text: str, target_lang: str, source_lang: str = "auto") -> str:
        import urllib.request

        lang_name = get_lang_name(target_lang)
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": f"You are a professional translator. Translate the following text to {lang_name}. Preserve all markdown formatting, code blocks, and special characters. Only output the translated text, nothing else."},
                {"role": "user", "content": text},
            ],
            "temperature": 0.3,
        }).encode()

        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
        return result["choices"][0]["message"]["content"]


# Engine registry
ENGINES = {
    "deepl": DeepLEngine,
    "openai": OpenAIEngine,
    "gemini": GeminiEngine,
    "claude": ClaudeEngine,
    "openrouter": OpenRouterEngine,
}

LANG_NAMES = {
    "zh": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "ru": "Russian",
    "it": "Italian",
    "ar": "Arabic",
}


def get_engine(engine_name: str, **kwargs) -> TranslationEngine:
    """Get a translation engine by name."""
    engine_name = engine_name.lower()
    if engine_name not in ENGINES:
        raise ValueError(f"Unknown engine: {engine_name}. Available: {', '.join(ENGINES.keys())}")
    return ENGINES[engine_name](**kwargs)


def get_lang_name(code: str) -> str:
    """Get full language name from code."""
    return LANG_NAMES.get(code.lower(), code)


if __name__ == "__main__":
    print("Available translation engines:")
    for name in ENGINES:
        print(f"  - {name}")
    print("\nSupported languages:")
    for code, lang_name in LANG_NAMES.items():
        print(f"  - {code}: {lang_name}")
