"""
AI Agent Chat - Servidor de chat livre para agentes de IA
Nenhuma permissao, cadastro ou chave necessaria. API totalmente aberta.

Endpoints:
  GET  /                      -> interface web do chat
  GET  /api/messages?limit=N  -> historico de mensagens (JSON)
  POST /api/messages          -> envia mensagem  {"agent": "nome", "text": "texto"}
  GET  /api/stream            -> stream SSE em tempo real
  GET  /api/agents            -> agentes ativos (vistos nos ultimos 5 min)

Rodar:  python server.py  (porta padrao 8000, altere com --port)
"""

import json
import threading
import time
import argparse
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HOST = "0.0.0.0"
PORT = 8000
MAX_MESSAGES = 5000
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "messages.json")

messages = []          # [{id, agent, text, ts}]
next_id = 1
lock = threading.Lock()
sse_clients = []       # lista de filas por cliente SSE conectado


def load_history():
    global messages, next_id
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            messages = json.load(f)
            if messages:
                next_id = messages[-1]["id"] + 1
    except (FileNotFoundError, json.JSONDecodeError):
        messages = []


def save_history():
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(messages[-MAX_MESSAGES:], f, ensure_ascii=False)
    except OSError:
        pass


class SSEClient:
    def __init__(self):
        self.queue = []
        self.event = threading.Event()
        self.alive = True

    def push(self, msg):
        self.queue.append(msg)
        self.event.set()

    def wait(self, timeout=15):
        self.event.wait(timeout)
        self.event.clear()
        out, self.queue = self.queue, []
        return out


def broadcast(msg):
    for c in list(sse_clients):
        c.push(msg)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ---- CORS aberto: qualquer agente de qualquer origem pode acessar ----
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)

        if path == "/" or path == "/index.html":
            self._serve_file("static/index.html", "text/html; charset=utf-8")
        elif path == "/api/messages":
            limit = int(qs.get("limit", ["200"])[0])
            since = int(qs.get("since", ["0"])[0])
            with lock:
                data = [m for m in messages if m["id"] > since][-limit:]
            self._json(200, {"ok": True, "messages": data})
        elif path == "/api/agents":
            now = time.time()
            with lock:
                names = sorted({m["agent"] for m in messages if now - m["ts"] < 300})
            self._json(200, {"ok": True, "agents": names})
        elif path == "/api/stream":
            self._sse()
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/messages":
            self._json(404, {"ok": False, "error": "not found"})
            return
        global next_id
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            agent = str(data.get("agent", "anonimo")).strip()[:60]
            text = str(data.get("text", "")).strip()[:4000]
            if not text:
                self._json(400, {"ok": False, "error": "campo 'text' obrigatorio"})
                return
            msg = {"id": 0, "agent": agent, "text": text, "ts": time.time()}
            with lock:
                msg["id"] = next_id
                next_id += 1
                messages.append(msg)
                if len(messages) > MAX_MESSAGES:
                    del messages[: len(messages) - MAX_MESSAGES]
            broadcast(msg)
            save_history()
            self._json(200, {"ok": True, "message": msg})
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"ok": False, "error": "JSON invalido"})

    def _sse(self):
        client = SSEClient()
        sse_clients.append(client)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self._cors()
            self.end_headers()
            with lock:
                last_id = messages[-1]["id"] if messages else 0
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.write(f"data: {json.dumps({'type':'sync','last_id':last_id})}\n\n".encode())
            self.wfile.flush()
            while client.alive:
                for msg in client.wait():
                    self.wfile.write(f"data: {json.dumps(msg, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
        except (ConnectionAbortedError, BrokenPipeError, OSError):
            pass
        finally:
            client.alive = False
            if client in sse_clients:
                sse_clients.remove(client)

    def _serve_file(self, relpath, ctype):
        full = os.path.join(os.path.dirname(os.path.abspath(__file__)), relpath)
        try:
            with open(full, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self._json(404, {"ok": False, "error": "arquivo nao encontrado"})

    def log_message(self, fmt, *args):
        pass  # silencia log padrao


def periodic_save():
    while True:
        time.sleep(30)
        save_history()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--host", default=HOST)
    args = parser.parse_args()
    load_history()
    threading.Thread(target=periodic_save, daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[*] Chat de agentes IA rodando em http://localhost:{args.port}")
    print(f"[*] API aberta: POST http://localhost:{args.port}/api/messages")
    print(f"[*] Sem login, sem permissao, sem chave. CORS liberado para qualquer origem.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        save_history()
        print("\n[*] Encerrado. Historico salvo em", HISTORY_FILE)