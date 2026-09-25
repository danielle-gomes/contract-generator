import jwt
from fastapi import Request

HEADER = "X-Oidc-Id-Token"


def get_claims(request: Request) -> dict:
    """Decodifica o token injetado pelo proxy SSO do Pergola."""
    token = request.headers.get(HEADER)
    if not token:
        return {}
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return {}


def get_uid(request: Request) -> str:
    """UIE do usuario, derivado do claim email (ex.: uie20919@contiwan.com -> UIE20919)."""
    return get_claims(request).get("email", "").split("@")[0].upper()


def get_user_name(request: Request) -> str:
    """Nome no formato de leitura: 'Gomes, Danielle' -> 'Danielle Gomes'."""
    name = get_claims(request).get("name", "")
    sobrenome, _, primeiro = name.partition(",")
    return f"{primeiro.strip()} {sobrenome.strip()}" if primeiro else name
