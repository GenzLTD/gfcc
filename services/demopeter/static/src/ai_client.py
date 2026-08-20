"""
szpeter2026 - AI 客户端
吸收自 Wukong ai_sql.py，统一 DeepSeek / Ollama 接口
"""
import time
import json
from typing import Generator

import httpx
from config.settings import config


class AIClient:
    """AI 模型统一客户端 — 支持 DeepSeek API 和 Ollama 本地模型"""

    def __init__(self, provider: str | None = None, *, validate: bool = True):
        self.provider = provider or config.AI_PROVIDER
        if validate:
            self._validate()

    @classmethod
    def is_configured(cls, provider: str | None = None) -> tuple[bool, str]:
        """检查 AI 是否可用，返回 (是否可用, 提示信息)。"""
        provider = provider or config.AI_PROVIDER
        if provider == "deepseek":
            if not config.DEEPSEEK_API_KEY:
                return False, (
                    "DEEPSEEK_API_KEY 未配置。请执行 cp .env.example .env "
                    "并填入密钥，或在 .env 中设置 AI_PROVIDER=ollama 使用本地模型。"
                )
        elif provider == "ollama":
            try:
                with httpx.Client(timeout=3) as client:
                    client.get(f"{config.OLLAMA_BASE_URL}/api/tags")
            except Exception:
                return False, (
                    f"Ollama 未运行（{config.OLLAMA_BASE_URL}）。"
                    "请先启动 Ollama，或配置 DEEPSEEK_API_KEY。"
                )
        else:
            return False, f"不支持的 AI 提供商: {provider}"
        return True, ""

    def _validate(self):
        ok, msg = self.is_configured(self.provider)
        if not ok:
            raise ValueError(msg)

    def chat(self, messages: list[dict], temperature: float = 0.7,
             max_tokens: int = 2000) -> tuple[str, float]:
        """同步对话，返回 (回复文本, 耗时秒)"""
        if self.provider == "deepseek":
            return self._chat_deepseek(messages, temperature, max_tokens)
        else:
            return self._chat_ollama(messages, temperature, max_tokens)

    def chat_stream(self, messages: list[dict], temperature: float = 0.7,
                    max_tokens: int = 2000) -> Generator[str, None, float]:
        """流式对话，返回生成器，最终 yield 耗时"""
        if self.provider == "deepseek":
            yield from self._stream_deepseek(messages, temperature, max_tokens)
        else:
            yield from self._stream_ollama(messages, temperature, max_tokens)

    # ===== DeepSeek =====

    def _chat_deepseek(self, messages: list[dict], temperature: float,
                       max_tokens: int) -> tuple[str, float]:
        start = time.time()
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{config.DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.DEEPSEEK_MODEL,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            elapsed = time.time() - start
            return data["choices"][0]["message"]["content"], elapsed

    def _stream_deepseek(self, messages: list[dict], temperature: float,
                         max_tokens: int) -> Generator[str, None, float]:
        start = time.time()
        with httpx.Client(timeout=120) as client:
            with client.stream(
                "POST",
                f"{config.DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.DEEPSEEK_MODEL,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        yield time.time() - start  # 最后一个元素是耗时

    # ===== Ollama =====

    def _chat_ollama(self, messages: list[dict], temperature: float,
                     max_tokens: int) -> tuple[str, float]:
        start = time.time()
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"{config.OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": config.OLLAMA_MODEL,
                    "messages": messages,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            elapsed = time.time() - start
            return data["message"]["content"], elapsed

    def _stream_ollama(self, messages: list[dict], temperature: float,
                       max_tokens: int) -> Generator[str, None, float]:
        start = time.time()
        with httpx.Client(timeout=120) as client:
            with client.stream(
                "POST",
                f"{config.OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": config.OLLAMA_MODEL,
                    "messages": messages,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    try:
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            yield data["message"]["content"]
                        if data.get("done"):
                            break
                    except (json.JSONDecodeError, KeyError):
                        continue
        yield time.time() - start
