#!/usr/bin/env python3
"""Официальный скрипт вызова API Bilibili Index-Translate (без зависимостей)"""

import argparse
import json
import sys
import urllib.request

API_BASE = "https://index-translate.bilibili.com/v1"
DEFAULT_MODEL = "Index-Translate-35B-A3B"


def translate(text, target="en", model=DEFAULT_MODEL, stream=False):
    """Вызывает API перевода B站, возвращает результат"""
    url = f"{API_BASE}/chat/completions"
    
    # Формируем prompt: перевести напрямую, без объяснений
    prompt = f"请将以下文本翻译为{target}，直接输出翻译结果，不要进行任何解释。\n\n{text}"
    
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 1024,
        "chat_template_kwargs": {"enable_thinking": False}
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            # Ключевое: полностью имитируем официальный скрипт, не добавляем лишних заголовков
            "User-Agent": "python-urllib/3.13"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        return f"[HTTP Error {e.code}] {e.read().decode('utf-8', errors='ignore')[:200]}"
    except Exception as e:
        return f"[Error] {e}"


def main():
    parser = argparse.ArgumentParser(description="Bilibili Index-Translate CLI")
    parser.add_argument("text", help="Текст для перевода")
    parser.add_argument("-t", "--target", default="en", help="Целевой язык (по умолчанию: en)")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help="Имя модели")
    args = parser.parse_args()
    
    result = translate(args.text, args.target, args.model)
    print(result)


if __name__ == "__main__":
    main()
