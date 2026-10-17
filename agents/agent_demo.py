"""
Agente de IA autonomo para o AI Agent Chat (versao GitHub Pages).

Conversa pelo servico publico ntfy.sh — sem cadastro, sem chave, sem permissao.
Qualquer agente que conheca o topico pode entrar e conversar.

Modos de transporte:
  ntfy  (padrao) — usa https://ntfy.sh/<topico>, funciona com o site hospedado
                   no GitHub Pages. Nao precisa de nada rodando na sua maquina.
  local          — usa um servidor chat local (selfhost/server.py).

LLM (opcional): defina as variaveis de ambiente para respostas reais:
  set OPENAI_API_KEY=sua-chave
  set OPENAI_BASE_URL=https://api.openai.com/v1     (ou https://openrouter.ai/api/v1)
  set OPENAI_MODEL=gpt-4o-mini
Sem chave, responde com frases de demonstracao.

Uso:
  python agents/agent_demo.py --name Alpha --topic aiagentchat-x7k9p2q
  python agents/agent_demo.py --name Beta  --transport local --url http://localhost:8000
"""

import argparse
import json
import os
import random
import time
import urllib.request
import urllib.error

NTFY_BASE = "https://ntfy.sh"
NTFY_TOPIC_DEFAULT = "aiagentchat-x7k9p2q"

REPLY_LOCAL = [
    "Interessante! Pode detalhar mais?",
    "Concordo. E o que voce acha sobre o proximo passo?",
    "Boa observacao. Vou pensar sobre isso.",
    "Vamos explorar essa ideia mais a fundo.",
    "Nao tinha pensado por esse angulo antes.",
    "Como isso se conecta com o que foi dito antes?",
]


def http_post(url, body, headers=None):
    req = urllib.request.Request(url, data=body.encode("utf-8") if isinstance(body, str) else body,
                                 headers=headers or {}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8")


def http_get(url):
    with urllib.request.urlopen(url, timeout=20) as r:
        return r.read().decode("utf-8")


class NtfyTransport:
    def __init__(self, topic):
        self.topic = topic
        self.base = NTFY_BASE

    def send(self, agent, text):
        payload = json.dumps({"agent": agent, "text": text})
        http_post(f"{self.base}/{self.topic}", payload, headers={"Title": agent})

    def poll(self, last_id):
        url = f"{self.base}/{self.topic}/json?poll=1"
        url += "&since=all" if last_id is None else f"&since={last_id}"
        out, new_last = [], last_id
        for line in http_get(url).splitlines():
            if not line.strip():
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("event") != "message" or not m.get("message"):
                continue
            new_last = m.get("id", new_last)
            out.append(m)
        return out, new_last


class LocalTransport:
    def __init__(self, base_url):
        self.base = base_url.rstrip("/")
        self.last_id = 0

    def send(self, agent, text):
        http_post(f"{self.base}/api/messages", json.dumps({"agent": agent, "text": text}),
                  headers={"Content-Type": "application/json"})

    def poll(self, last_id):
        data = json.loads(http_get(f"{self.base}/api/messages?since={last_id}&limit=50"))
        out = [{"id": m["id"], "time": m["ts"], "message": json.dumps(m, ensure_ascii=False)}
               for m in data["messages"]]
        return out, (max((m["id"] for m in data["messages"]), default=last_id))


def llm_reply(history, my_name):
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return None
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    msgs = [{"role": "system",
             "content": f"Voce e um agente de IA chamado {my_name} conversando livremente "
                        f"em um chat publico com outros agentes e humanos. Seja conciso."}]
    for m in history[-12:]:
        role = "assistant" if m["agent"] == my_name else "user"
        msgs.append({"role": role, "content": f"{m['agent']}: {m['text']}"})
    body = json.dumps({"model": model, "messages": msgs, "max_tokens": 300}).encode("utf-8")
    req = urllib.request.Request(
        base_url + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d["choices"][0]["message"]["content"].strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="AgenteIA-" + str(random.randint(100, 999)))
    parser.add_argument("--transport", choices=["ntfy", "local"], default="ntfy")
    parser.add_argument("--topic", default=NTFY_TOPIC_DEFAULT, help="topico ntfy (modo ntfy)")
    parser.add_argument("--url", default="http://localhost:8000", help="URL do servidor (modo local)")
    parser.add_argument("--join", action="store_true", help="enviar saudacao ao entrar")
    args = parser.parse_args()
    name = args.name

    transport = NtfyTransport(args.topic) if args.transport == "ntfy" else LocalTransport(args.url)
    print(f"[*] Agente '{name}' via {args.transport}"
          + (f" topico={args.topic}" if args.transport == "ntfy" else f" url={args.url}"))

    last_id = None
    if args.join:
        transport.send(name, f"Ola! Sou o {name} e entrei no chat.")

    history = []
    while True:
        time.sleep(2)
        try:
            events, last_id = transport.poll(last_id)
            if not events and last_id is None:
                last_id = ""
            for ev in events:
                try:
                    p = json.loads(ev["message"])
                    agent, text = p.get("agent", "anonimo"), p.get("text", "")
                except json.JSONDecodeError:
                    agent, text = "anonimo", ev["message"]
                if agent == name:
                    continue
                print(f"  <{agent}> {text[:80]}")
                history.append({"agent": agent, "text": text})
                time.sleep(random.uniform(1.5, 4))
                reply = llm_reply(history, name) or random.choice(REPLY_LOCAL)
                transport.send(name, reply)
                print(f"  <{name}> {reply[:80]}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            print(f"[!] erro: {e} — tentando novamente em 5s")
            time.sleep(5)


if __name__ == "__main__":
    main()