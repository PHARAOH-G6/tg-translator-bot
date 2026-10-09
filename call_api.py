#!/usr/bin/env python3
"""Локальный прокси для Bilibili Index-Translate API.
Принимает запросы от бота и пересылает их в B站 с чистыми заголовками."""

import json
import logging
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

BILIBILI_API = "https://index-translate.bilibili.com/v1/chat/completions"
BILIBILI_MODEL = "Index-Translate-35B-A3B"
PROXY_PORT = 8080

logging.basicConfig(level=logging.INFO, format="%(asctime)s [proxy] %(message)s")


class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Подавляем стандартные логи http.server, чтобы не засорять
        pass

    def do_POST(self):
        try:
            # Читаем запрос от бота
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body.decode("utf-8"))

            # Формируем запрос к B站
            payload = json.dumps({
                "model": BILIBILI_MODEL,
                "messages": data.get("messages", []),
                "temperature": 0,
                "max_tokens": 1024,
                "chat_template_kwargs": {"enable_thinking": False}
            }).encode("utf-8")

            req = urllib.request.Request(
                BILIBILI_API,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                result = resp.read()
                logging.info("Успешный перевод через B站")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(result)

        except urllib.error.HTTPError as e:
            logging.warning(f"B站 вернул HTTP {e.code}")
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            logging.exception(f"Ошибка прокси: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PROXY_PORT), ProxyHandler)
    logging.info(f"Прокси-сервер запущен на порту {PROXY_PORT}")
    server.serve_forever()
