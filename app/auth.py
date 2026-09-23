import jwt
from fastapi import Request, HTTPException

GROUP_PREFIX = "ti_br_ju_contracts"   # ajuste pro prefixo dos seus grupos no SMT


def get_user(request: Request) -> dict:
    token = request.headers.get("X-Oidc-Id-Token")
    if not token:
        raise HTTPException(401, "SSO header ausente")

    claims = jwt.decode(token, options={"verify_signature": False})
    groups = [g for g in claims.get("groups", []) if g.startswith(GROUP_PREFIX)]

    if not groups:
        raise HTTPException(403, "Você não pertence ao grupo AD necessário")

    return {
        "email": claims.get("email"),
        "uie": (claims.get("email") or "").split("@")[0].upper(),
        "groups": groups,
    }