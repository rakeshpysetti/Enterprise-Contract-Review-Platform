"""Provisioned bearer identities; tenant membership is always server controlled."""

import hashlib
import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

bearer = HTTPBearer(auto_error=False)


class Principal(BaseModel):
    user_id: str
    tenant_id: str
    role: str
    authentication_required: bool = True


def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    settings = request.app.state.settings
    required = (
        bool(settings.auth_accounts)
        or settings.require_auth
        or (settings.app_env == "production")
    )
    if not required:
        return Principal(
            user_id="local-developer",
            tenant_id="legacy",
            role="reviewer",
            authentication_required=False,
        )
    if not settings.auth_accounts:
        raise HTTPException(503, "Access accounts have not been configured")
    if credentials is not None:
        digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        for account in settings.auth_accounts:
            if hmac.compare_digest(digest, account.token_sha256.get_secret_value()):
                return Principal(
                    user_id=account.user_id,
                    tenant_id=account.tenant_id,
                    role=account.role,
                )
    raise HTTPException(
        401, "A valid access key is required", headers={"WWW-Authenticate": "Bearer"}
    )
