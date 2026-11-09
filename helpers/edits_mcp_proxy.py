#!/usr/bin/env python3
"""Ponte stdio ↔ servidor de automação do app Edits (Meta), para clientes MCP.

Por que existe: o Edits responde com `resultType: "complete"` e o cliente do
Claude Code, ao ver esse campo, passa a exigir `ttlMs` e `cacheScope`, que o app
não manda. O `tools/list` é rejeitado e nenhuma ferramenta aparece. Esta ponte
tira o campo das respostas e repassa o resto sem tocar.

Faz mais duas coisas que o HTTP direto não faz:
- O conjunto de ferramentas segue a tela do app (32 na home, 274 no editor). A
  ponte confere a lista e avisa o cliente com `notifications/tools/list_changed`.
- Com o app fechado, a sessão continua de pé com a lista vazia e a chamada
  devolve o que fazer, em vez de o servidor constar como quebrado até reiniciar.

O token vem de EDITS_MCP_TOKEN ou do item `edits-mcp-token` do Chaves do macOS.
Nunca fica neste arquivo. Se ele clicar em Regenerate no app:
    security add-generic-password -U -s edits-mcp-token -a "$USER" -w <novo token>

Só biblioteca padrão: é iniciada a cada sessão do agente.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request

ENDPOINT = os.environ.get("EDITS_MCP_URL", "http://127.0.0.1:19501/mcp")
KEYCHAIN_SERVICE = "edits-mcp-token"
POLL_SECONDS = 5.0
TIMEOUT_SECONDS = 600.0  # export e transcrição seguram a resposta
PROTOCOL = "2025-03-26"
OFFLINE = ("O Edits não respondeu em 127.0.0.1:19501. Abra o app e confira "
           "Ajustes > Automation > Enable Automation Server.")
UNAUTHORIZED = ("O Edits recusou o token. Rode: security add-generic-password -U "
                "-s edits-mcp-token -a \"$USER\" -w <token de Ajustes > Automation>")


def read_token() -> str:
    token = os.environ.get("EDITS_MCP_TOKEN", "").strip()
    if token:
        return token
    done = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True, check=False)
    return done.stdout.strip()


def clean(message):
    """Tira `resultType` da resposta; é o único campo que o cliente rejeita."""
    if isinstance(message, dict) and isinstance(message.get("result"), dict):
        message["result"].pop("resultType", None)
    return message


class Offline(Exception):
    pass


class Unauthorized(Exception):
    pass


def post(payload: dict, token: str, timeout: float = TIMEOUT_SECONDS):
    """Manda uma mensagem ao app. Devolve o JSON, ou None se não houver corpo."""
    request = urllib.request.Request(
        ENDPOINT, json.dumps(payload).encode(),
        {"Content-Type": "application/json", "Accept": "application/json",
         "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            body = reply.read()
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise Unauthorized from error
        raise Offline from error
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise Offline from error
    return json.loads(body) if body.strip() else None


def tool_names(listing) -> frozenset[str]:
    tools = ((listing or {}).get("result") or {}).get("tools") or []
    return frozenset(tool.get("name", "") for tool in tools)


def offline_reply(message: dict, text: str) -> dict | None:
    """O que responder sem o app: a sessão fica de pé, a chamada explica."""
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL,
                  "capabilities": {"tools": {"listChanged": True}},
                  "serverInfo": {"name": "edits-proxy", "version": "1"},
                  "instructions": text}
    elif method == "tools/list":
        result = {"tools": []}
    elif method == "tools/call":
        result = {"isError": True, "content": [{"type": "text", "text": text}]}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": ident,
                "error": {"code": -32000, "message": text}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


class Proxy:
    def __init__(self, token: str) -> None:
        self.token = token
        self.write_lock = threading.Lock()
        self.known: frozenset[str] | None = None
        self.stop = threading.Event()

    def emit(self, message: dict) -> None:
        with self.write_lock:
            sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def current_tools(self) -> frozenset[str]:
        try:
            return tool_names(post(
                {"jsonrpc": "2.0", "id": "poll", "method": "tools/list"},
                self.token, timeout=10))
        except (Offline, Unauthorized, ValueError):
            return frozenset()

    def watch(self) -> None:
        """Avisa o cliente quando a tela do app muda o conjunto de ferramentas."""
        while not self.stop.wait(POLL_SECONDS):
            now = self.current_tools()
            if self.known is not None and now != self.known:
                self.known = now
                self.emit({"jsonrpc": "2.0",
                           "method": "notifications/tools/list_changed"})

    def handle(self, message: dict) -> None:
        try:
            reply = clean(post(message, self.token))
        except Offline:
            reply = offline_reply(message, OFFLINE)
        except Unauthorized:
            reply = offline_reply(message, UNAUTHORIZED)
        except ValueError:
            reply = offline_reply(message, "Resposta inválida do Edits.")
        if message.get("method") == "tools/list" and reply is not None:
            self.known = tool_names(reply)
        if reply is not None and message.get("id") is not None:
            self.emit(reply)

    def run(self) -> None:
        threading.Thread(target=self.watch, daemon=True).start()
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue
            # Em paralelo: um export demorado não pode travar ping nem outra chamada.
            threading.Thread(target=self.handle, args=(message,), daemon=True).start()
        self.stop.set()


if __name__ == "__main__":
    Proxy(read_token()).run()
