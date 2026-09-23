import base64, json
from fastapi import Request, HTTPException

USER_HEADERS  = ("x-auth-request-preferred-username", "x-auth-request-user", "x-forwarded-user")
EMAIL_HEADERS = ("x-auth-request-email", "x-forwarded-email")
TOKEN_HEADERS = ("x-auth-request-access-token", "x-forwarded-access-token", "x-auth-request-id-token")


def _jwt_payload(token: str) -> dict:
    p = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


def current_user(request: Request) -> dict:
    h = request.headers

    uie   = next((h[k] for k in USER_HEADERS if k in h), None)
    email = next((h[k] for k in EMAIL_HEADERS if k in h), None)
    name  = None

    # fallback: o proxy já validou a assinatura, aqui só lemos os claims
    token = next((h[k] for k in TOKEN_HEADERS if k in h), None)
    if token:
        c = _jwt_payload(token)
        uie   = uie   or c.get("preferred_username") or c.get("upn") or c.get("sub")
        email = email or c.get("email") or c.get("upn")
        name  = c.get("name")

    if not uie:
        raise HTTPException(401, "Usuário não identificado pelo SSO")

    return {"uie": uie.split("@")[0].upper(), "email": email, "name": name}