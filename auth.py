"""OAuth token management for Mercado Livre — auto-refresh incluído."""

import json
import time
from pathlib import Path

import httpx

TOKEN_FILE = Path.home() / ".mercado-livre-analytics" / "tokens.json"
ML_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
_EXPIRY_BUFFER = 300  # renova 5 min antes do vencimento


def load_tokens() -> dict:
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_tokens(tokens: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))


def _is_expired(tokens: dict) -> bool:
    return time.time() >= (tokens.get("expires_at", 0) - _EXPIRY_BUFFER)


async def _do_refresh(client_id: str, client_secret: str, refresh_token: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            ML_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        data["expires_at"] = time.time() + data.get("expires_in", 21600)
        return data


async def get_valid_access_token(client_id: str, client_secret: str) -> str:
    """Retorna um access token válido, renovando via refresh_token se necessário."""
    tokens = load_tokens()

    if not tokens or "access_token" not in tokens:
        raise RuntimeError(
            "Tokens não encontrados. Execute primeiro:\n"
            "  uv run auth_setup.py"
        )

    if _is_expired(tokens):
        refresh_tok = tokens.get("refresh_token")
        if not refresh_tok:
            raise RuntimeError(
                "Refresh token ausente. Execute novamente:\n"
                "  uv run auth_setup.py"
            )
        new_tokens = await _do_refresh(client_id, client_secret, refresh_tok)
        # ML pode rotacionar o refresh_token — preserva o novo se vier
        tokens.update(new_tokens)
        save_tokens(tokens)

    return tokens["access_token"]


def get_seller_id() -> str:
    """Retorna o user_id gravado no token (= seller_id do vendedor autenticado)."""
    tokens = load_tokens()
    user_id = tokens.get("user_id")
    if not user_id:
        raise RuntimeError(
            "user_id não encontrado. Execute:\n"
            "  uv run auth_setup.py"
        )
    return str(user_id)
