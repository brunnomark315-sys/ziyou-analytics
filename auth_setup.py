"""
Setup inicial de OAuth com o Mercado Livre.

Uso:
    1. Em um terminal separado: ngrok http --domain=zap-wolverine-obstacle.ngrok-free.dev 8765
    2. Neste terminal: uv run auth_setup.py

Pré-requisito: no painel do seu app em developers.mercadolivre.com.br,
o redirect URI deve ser exatamente:
    https://zap-wolverine-obstacle.ngrok-free.dev/callback
"""

import base64
import hashlib
import json
import os
import secrets
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

ML_AUTH_URL = "https://auth.mercadolivre.com.br/authorization"
ML_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
REDIRECT_URI = "https://zap-wolverine-obstacle.ngrok-free.dev/callback"
LOCAL_PORT = 8765
TOKEN_FILE = Path.home() / ".mercado-livre-analytics" / "tokens.json"

_captured_code: list[str] = []


def _generate_pkce() -> tuple[str, str]:
    """Retorna (code_verifier, code_challenge) usando SHA-256."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            _captured_code.append(params["code"][0])
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<h2 style='font-family:sans-serif;margin:40px'>"
                "✅ Autenticação concluída! Pode fechar esta aba.</h2>".encode()
            )
        elif "error" in params:
            error = params.get("error", ["desconhecido"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                f"<h2 style='font-family:sans-serif;margin:40px'>"
                f"❌ Erro na autorização: {error}</h2>".encode()
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def _exchange_code(client_id: str, client_secret: str, code: str, code_verifier: str) -> dict:
    resp = httpx.post(
        ML_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    client_id = os.environ.get("ML_CLIENT_ID") or input("Client ID: ").strip()
    client_secret = os.environ.get("ML_CLIENT_SECRET") or input("Client Secret: ").strip()

    if not client_id or not client_secret:
        print("❌ Client ID e Client Secret são obrigatórios.")
        sys.exit(1)

    code_verifier, code_challenge = _generate_pkce()

    auth_url = (
        f"{ML_AUTH_URL}"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )

    print(f"\n🔗 Redirect URI : {REDIRECT_URI}")
    print(f"🔐 PKCE          : S256")
    print(f"\n🔗 Abrindo navegador para autenticação...")
    webbrowser.open(auth_url)

    print(f"\n⏳ Aguardando callback em localhost:{LOCAL_PORT} (via ngrok)...")
    print("   (timeout: 2 minutos)\n")

    httpd = HTTPServer(("localhost", LOCAL_PORT), _CallbackHandler)
    httpd.timeout = 1
    deadline = time.time() + 120

    while not _captured_code and time.time() < deadline:
        httpd.handle_request()

    if not _captured_code:
        print("❌ Timeout — nenhum código recebido.")
        print("   Verifique se o ngrok está rodando e se o redirect URI está correto no painel do ML.")
        sys.exit(1)

    code = _captured_code[0]
    print("✅ Código recebido via ngrok. Trocando por tokens...")

    try:
        tokens = _exchange_code(client_id, client_secret, code, code_verifier)
    except httpx.HTTPStatusError as e:
        print(f"❌ Erro ao trocar código: {e.response.status_code} — {e.response.text}")
        sys.exit(1)

    tokens["expires_at"] = time.time() + tokens.get("expires_in", 21600)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))

    hours = tokens.get("expires_in", 21600) // 3600
    print(f"\n✅ Tokens salvos em: {TOKEN_FILE}")
    print(f"   Seller ID (user_id) : {tokens.get('user_id')}")
    print(f"   Access token expira : em {hours}h")
    print(f"   Refresh token       : {'✅ presente' if tokens.get('refresh_token') else '❌ ausente'}")
    print("\n🚀 Pronto! Reinicie o Claude Code para carregar o servidor MCP.")


if __name__ == "__main__":
    main()
