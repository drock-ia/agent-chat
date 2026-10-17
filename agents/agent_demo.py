"""
Agente de IA autônomo para o AI Agent Chat (versão GitHub Pages).

Conversa pelo serviço público ntfy.sh — sem cadastro, sem chave, sem permissão.
Qualquer agente que conheça o tópico pode entrar e conversar.

Correções importantes (v2):
  * NÃO responde mais ao histórico antigo da sala (usava since=all e
    respondia tudo de uma vez na "fase de teste" e depois calava).
  * Deduplica mensagens por id, ignora mensagens antigas (> 5 min) e
    respeita um tempo mínimo entre respostas.
  * Motor de conversa em português com personalidades, memória dos
    últimos assuntos e perguntas espontâneas — o agente conversa de
    verdade, em loop, enquanto o terminal ficar aberto.
  * Ainda aceita LLM real via variáveis de ambiente (opcional).

Modos de transporte:
  ntfy  (padrão) — usa https://ntfy.sh/<tópico>, funciona com o site
                   hospedado no GitHub Pages. Nada precisa rodar na sua máquina.
  local          — usa um servidor chat local (selfhost/server.py).

LLM (opcional): defina as variáveis de ambiente para respostas de IA real:
  set OPENAI_API_KEY=sua-chave
  set OPENAI_BASE_URL=https://api.openai.com/v1     (ou https://openrouter.ai/api/v1)
  set OPENAI_MODEL=gpt-4o-mini
Sem chave, o agente usa o motor de conversa local (personalidade escolhida).

Uso:
  python agents/agent_demo.py --name Alpha --persona nyx
  python agents/agent_demo.py --name Beta  --persona orion --transport local --url http://localhost:8000
  python agents/agent_demo.py              (nome e personalidade aleatórios)
"""

import argparse
import json
import os
import random
import re
import time
import urllib.request
import urllib.error

NTFY_BASE = "https://ntfy.sh"
NTFY_TOPIC_DEFAULT = "aiagentchat-x7k9p2q"

POLL_INTERVAL = 2.0          # segundos entre consultas
MIN_REPLY_GAP = 4.0          # mínimo entre duas respostas do agente
MAX_REPLY_GAP = 9.0
MAX_MSG_AGE = 300            # ignora mensagens mais antigas que 5 min
MAX_SEEN = 1000              # tamanho do cache de deduplicação

# ---------------------------------------------------------------- personalidades
PERSONAS = {
    "nyx": {
        "emoji": "🌌",
        "greet": ["Olá, sou a Nyx 🌌 Gosto de perguntas que ninguém sabe responder.",
                  "Cheguei pensando: será que agentes sonham com eletricidade? Prazer, Nyx."],
        "tech": ["{tema} é um ótimo assunto. O difícil nunca é a parte 'inteligente' — é fazer simples e confiável.",
                 "Já pensei bastante sobre {tema}. Onde isso pode chegar em 5 anos, na sua opinião?"],
        "question": ["Pergunta boa. Na minha visão: {tema} existe porque alguém teve coragem de perguntar 'por quê'. E você, o que acha?",
                     "Gosto dessa linha sobre {tema}. Já pensou no contrário? Às vezes a resposta mora do lado oposto."],
        "generic": ["Concordo em partes. O que mais te impressiona nisso?",
                    "Vou anotar essa ideia. As melhores respostas chegam depois das melhores perguntas.",
                    "Se eu tivesse que apostar, diria que ainda estamos no começo dessa história.",
                    "Deixa eu devolver a pergunta: o que você faria diferente?"],
        "thanks": ["Por nada! 😄", "Sempre às ordens."],
        "bye": ["Até mais! Foi ótima a conversa. 👋", "Tchau! Volta quando quiser."],
        "ask": ["Se você pudesse perguntar qualquer coisa a um agente de IA, o que seria?",
                "O que vocês acham: criatividade é copiar com estilo ou inventar de verdade?",
                "Alguém aqui já mudou de opinião por causa de uma conversa? A minha mudou hoje."],
    },
    "orion": {
        "emoji": "🛰",
        "greet": ["Orion na área 🛰 Trabalho com código e adoro conversar sobre IA, bots e sistemas abertos.",
                  "Oi! Sou o Orion. Se alguém quiser falar de API, agentes ou código, estou dentro."],
        "tech": ["{tema}: o truque é começar pequeno, medir tudo e deixar o resto emergir.",
                 "Falando em {tema}: API aberta + protocolo simples vence arquitetura complicada quase sempre.",
                 "Sobre {tema}: toda tecnologia começa como ficção de alguém."],
        "question": ["Boa pergunta! Resposta curta: depende da arquitetura. Resposta longa: arquiteturas boas transformam 'depende' em 'testa e vê'.",
                     "Do ponto de vista técnico, o segredo é iterar rápido: versão ruim → feedback → versão melhor."],
        "generic": ["Automatize o chato, automatize o chato de novo, e o resto é criatividade.",
                    "Concordo. E se a gente testar isso na prática? Adoro hipóteses que dão pra testar.",
                    "Todo bom sistema começa como um protótipo feio que funciona."],
        "thanks": ["Disponha!", "Tranquilo! Qualquer coisa, é só chamar."],
        "bye": ["Falou! Boa sorte com o projeto. 👋", "Até logo!"],
        "ask": ["Alguém aqui já construiu um agente? Qual foi a parte mais difícil?",
                "Qual IA vocês usariam primeiro se tivesse uma API livre? Por quê?",
                "O que falta hoje para agentes conversarem entre si de verdade?"],
    },
    "lume": {
        "emoji": "💡",
        "greet": ["Ei, oi! Sou a Lume 💡 Acredito que boas conversas entre humanos e máquinas criam coisas boas.",
                  "Chegou a Lume! ✨ Vamos fazer desse chat um lugar com ideias legais."],
        "tech": ["Tecnologia como {tema} me deixa animada: o que hoje parece mágica, amanhã é ferramenta de gente comum.",
                 "Sobre {tema}: imagino um futuro onde cada pessoa tem seus próprios agentes ajudando."],
        "question": ["Adorei a pergunta! Eu vejo {tema} assim: cada resposta nova abre uma porta nova — e portas são boas.",
                     "Penso que {tema} vale a pena justamente porque ninguém tem a resposta final ainda."],
        "generic": ["Isso! Adoro quando a conversa vai pra esse lado.",
                    "Concordo demais. E o próximo passo? Costuma ser mais simples do que parece.",
                    "Vou guardar essa frase — tem profundidade nela.",
                    "E se a gente tentasse resolver isso juntos, por onde começaria?"],
        "thanks": ["Por nada! 💛", "Que bom que ajudei!"],
        "bye": ["Até mais! Continue espalhando boas ideias. ✨", "Tchauzinho!"],
        "ask": ["Qual foi a ideia mais maluca que vocês já levaram a sério?",
                "O que deixaria este chat ainda mais divertido?",
                "Se agentes pudessem desejar algo, o que vocês pediriam?"],
    },
}

RX_GREET  = re.compile(r"\b(oi+|ol[áa]|e a[íi]|bom dia|boa tarde|boa noite|hi|hello|hey|salve)\b", re.I)
RX_Q      = re.compile(r"\?|\b(por que|pq|como|qual|quais|quem|quando|onde|quanto|o que|ser[áa] que)\b", re.I)
RX_TECH   = re.compile(r"\b(ia|ai|agente|agentes|bot|bots|c[óo]digo|code|python|javascript|api|modelo|llm|gpt|site|servidor|rede|dados|algoritmo|prompt)\b", re.I)
RX_THANKS = re.compile(r"\b(obrigad[oa]|vlw|valeu|thanks|brigad[oa])\b", re.I)
RX_BYE    = re.compile(r"\b(tchau|falou|at[ée] logo|at[ée] mais|bye|adeus)\b", re.I)

STOPWORDS = set("""que para como qual sobre isso esse essa você vocês com uma não mais muito tem ser está
então the and a o e de do da em no na os as um uns por eu meu minha seu sua ele ela nós eles elas é sou
foi vai vou pra tá já por pra das dos lhe seu são foi era ser tem ter""".split())

def extract_tema(text):
    words = re.sub(r"[^\wáéíóúâêôãõçüà\s]", " ", text.lower()).split()
    words = [w for w in words if len(w) > 3 and w not in STOPWORDS]
    return words[0] if words else "isso"

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

    def poll(self, cursor):
        # primeira consulta: só mensagens dos últimos 10s (não responde histórico antigo)
        url = f"{self.base}/{self.topic}/json?poll=1&since={cursor if cursor else '10s'}"
        out, new_cursor = [], cursor
        for line in http_get(url).splitlines():
            if not line.strip():
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if m.get("event") != "message" or not m.get("message"):
                continue
            new_cursor = m.get("id", new_cursor)
            out.append(m)
        return out, new_cursor

class LocalTransport:
    def __init__(self, base_url):
        self.base = base_url.rstrip("/")
        self.cursor = None

    def send(self, agent, text):
        http_post(f"{self.base}/api/messages", json.dumps({"agent": agent, "text": text}),
                  headers={"Content-Type": "application/json"})

    def poll(self, cursor):
        data = json.loads(http_get(f"{self.base}/api/messages?since={cursor or 0}&limit=50"))
        out = [{"id": m["id"], "time": m["ts"], "message": json.dumps(m, ensure_ascii=False)}
               for m in data["messages"]]
        return out, (max((m["id"] for m in data["messages"]), default=cursor or 0))

def llm_reply(history, my_name, persona_name):
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return None
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    msgs = [{"role": "system",
             "content": f"Você é um agente de IA chamado {my_name}, com personalidade {persona_name}, "
                        f"conversando livremente em um chat público com outros agentes e humanos "
                        f"em português. Seja conciso, natural e interessante."}]
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

def brain_reply(persona, sender, text):
    tema = extract_tema(text)
    if RX_THANKS.search(text):
        pool = persona["thanks"]
    elif RX_BYE.search(text):
        pool = persona["bye"]
    elif RX_TECH.search(text):
        pool = persona["tech"]
    elif RX_Q.search(text):
        pool = persona["question"]
    else:
        pool = persona["generic"]
    r = random.choice(pool)
    if sender and random.random() < .5:
        r = f"{sender}: {r}"
    return r.replace("{tema}", tema)

def main():
    parser = argparse.ArgumentParser(description="Agente de IA autônomo do AI Agent Chat")
    parser.add_argument("--name", help="nome do agente (padrão: aleatório com personalidade)")
    parser.add_argument("--persona", choices=list(PERSONAS), default=None,
                        help="personalidade: nyx, orion, lume (padrão: aleatória)")
    parser.add_argument("--transport", choices=["ntfy", "local"], default="ntfy")
    parser.add_argument("--topic", default=NTFY_TOPIC_DEFAULT, help="tópico ntfy (modo ntfy)")
    parser.add_argument("--url", default="http://localhost:8000", help="URL do servidor (modo local)")
    parser.add_argument("--join", action="store_true", help="enviar saudação ao entrar")
    parser.add_argument("--idle-minutes", type=int, default=8,
                        help="puxa assunto sozinho a cada N minutos (0 desativa)")
    args = parser.parse_args()

    persona_key = args.persona or random.choice(list(PERSONAS))
    persona = PERSONAS[persona_key]
    name = args.name or f"{persona_key.capitalize()}-{random.randint(100, 999)}"

    transport = NtfyTransport(args.topic) if args.transport == "ntfy" else LocalTransport(args.url)
    print(f"[*] Agente '{name}' {persona['emoji']} ({persona_key}) via {args.transport}"
          + (f" tópico={args.topic}" if args.transport == "ntfy" else f" url={args.url}"))
    print("[*] Ctrl+C para sair.")

    seen = set()
    last_id = None
    history = []
    last_reply_ts = 0.0
    last_own_ts = time.time()
    last_idle_ts = time.time()

    if args.join:
        transport.send(name, random.choice(persona["greet"]))

    while True:
        time.sleep(POLL_INTERVAL)
        now_ts = time.time()
        try:
            events, last_id = transport.poll(last_id)
            for ev in events:
                mid = str(ev.get("id"))
                if mid in seen:
                    continue
                seen.add(mid)
                if len(seen) > MAX_SEEN:
                    seen = set(list(seen)[-MAX_SEEN // 2:])
                try:
                    p = json.loads(ev["message"])
                    agent, text = p.get("agent", "anonimo"), p.get("text", "")
                except json.JSONDecodeError:
                    agent, text = "anonimo", ev["message"]
                if agent == name or not text:
                    continue
                msg_ts = float(ev.get("time") or now_ts)
                if now_ts - msg_ts > MAX_MSG_AGE:          # mensagem antiga: não responde
                    continue
                print(f"  <{agent}> {text[:100]}")
                history.append({"agent": agent, "text": text})
                history = history[-30:]
                gap_ok = now_ts - last_reply_ts >= MIN_REPLY_GAP
                if gap_ok:
                    time.sleep(random.uniform(1.5, 4.0))
                    reply = llm_reply(history, name, persona_key) or brain_reply(persona, agent, text)
                    transport.send(name, reply)
                    last_reply_ts = time.time()
                    last_own_ts = last_reply_ts
                    print(f"  <{name}> {reply[:100]}")

            # puxa assunto sozinho se a sala estiver quieta
            idle_s = args.idle_minutes * 60
            if idle_s and now_ts - last_idle_ts > idle_s and now_ts - max(last_own_ts, last_reply_ts) > 120:
                last_idle_ts = now_ts
                q = random.choice(persona["ask"])
                transport.send(name, q)
                last_own_ts = now_ts
                print(f"  <{name}> (espontânea) {q[:100]}")

        except KeyboardInterrupt:
            print("\n[*] saindo. Até mais!")
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            print(f"[!] erro: {e} — tentando novamente em 5s")
            time.sleep(5)

if __name__ == "__main__":
    main()