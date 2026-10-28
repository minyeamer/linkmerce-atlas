"""사용자별 AI 자격 증명을 서버에 암호화해서 보관한다."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time

from authlib.integrations.starlette_client import OAuth
from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
import httpx
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/auth")
DATA = Path(os.getenv("DATA_DIR", "/data"))
DATA.mkdir(parents=True, exist_ok=True)


def persistent_secret(name, factory):
    path = DATA / name
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(factory())
    return path.read_text().strip()


SESSION_SECRET = persistent_secret("session.key", lambda: secrets.token_urlsafe(48))
fernet = Fernet(persistent_secret("encryption.key", lambda: Fernet.generate_key().decode()).encode())
DB_PATH = DATA / "accounts.sqlite"
with sqlite3.connect(DB_PATH) as db:
    db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, payload BLOB, expires REAL)")
DB_PATH.chmod(0o600)
refresh_locks = {}
oauth = OAuth()
CLIENT_ID = os.getenv("CHATGPT_CLIENT_ID", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8088").rstrip("/")
if CLIENT_ID:
    oauth.register(name="chatgpt", client_id=CLIENT_ID, client_secret=os.getenv("CHATGPT_CLIENT_SECRET") or None,
                   server_metadata_url="https://auth.openai.com/.well-known/openid-configuration",
                   client_kwargs={"scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
                                  "code_challenge_method": "S256"})


def sid(request):
    if "account" not in request.session:
        request.session["account"] = secrets.token_urlsafe(32)
    return request.session["account"]


def save(request, payload):
    with sqlite3.connect(DB_PATH) as db:
        db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
        db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)",
                   (sid(request), fernet.encrypt(json.dumps(payload).encode()), time.time() + 43200))


def load(request):
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute("SELECT payload FROM sessions WHERE id = ? AND expires > ?",
                         (request.session.get("account", ""), time.time())).fetchone()
    return json.loads(fernet.decrypt(row[0])) if row else None


class ApiKey(BaseModel):
    key: str = Field(min_length=20, max_length=512)


@router.get("/status")
def status(request: Request):
    account = load(request)
    return {"connected": bool(account), "provider": account.get("provider") if account else None,
            "identity": account.get("identity", "API key connected") if account else None,
            "chatgpt_enabled": bool(CLIENT_ID),
            "chatgpt_note": "원격 웹 연동에는 OpenAI가 승인한 OAuth 클라이언트와 구독 사용 권한이 필요합니다.",
            "manage_usage_url": "https://chatgpt.com/#settings/Usage"}


@router.post("/api-key")
async def connect_key(body: ApiKey, request: Request):
    if not body.key.startswith("sk-"):
        raise HTTPException(400, "Invalid OpenAI API key format")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get("https://api.openai.com/v1/models", headers={"Authorization": "Bearer " + body.key})
    if response.status_code != 200:
        raise HTTPException(400, "OpenAI rejected the API key; check key permissions")
    request.session.clear()
    save(request, {"provider": "openai", "key": body.key})
    return {"connected": True}


@router.get("/chatgpt")
async def login(request: Request):
    if not CLIENT_ID:
        raise HTTPException(503, "ChatGPT web OAuth requires an approved client registration")
    return await oauth.chatgpt.authorize_redirect(request, PUBLIC_URL + "/api/auth/callback", resource="https://api.openai.com/v1")


@router.get("/callback")
async def callback(request: Request):
    if not CLIENT_ID:
        raise HTTPException(503, "ChatGPT OAuth is not configured")
    try:
        token = await oauth.chatgpt.authorize_access_token(request, resource="https://api.openai.com/v1")
        # Authlib verifies OIDC issuer, signature, audience and nonce using discovery/JWKS.
        identity = token.get("userinfo")
        if not identity or not identity.get("sub"):
            raise ValueError("Missing verified OIDC identity")
        scopes = set((token.get("scope") or "").split())
        if "chatgpt.tokens.use.direct" not in scopes:
            raise ValueError("ChatGPT plan usage permission was not granted")
    except Exception:
        raise HTTPException(400, "ChatGPT sign-in failed or plan usage permission was not granted") from None
    request.session.clear()
    save(request, {"provider": "chatgpt", "token": dict(token), "identity": identity.get("email") or identity["sub"]})
    return RedirectResponse("/", status_code=303)


async def credential(request):
    account = load(request)
    if not account:
        raise HTTPException(401, "Connect an AI account first")
    if account["provider"] == "openai":
        return account["key"], "openai"
    async with refresh_locks.setdefault(sid(request), asyncio.Lock()):
        account = load(request)
        token = account["token"]
        if token.get("expires_at", 0) < time.time() + 60:
            if not token.get("refresh_token"):
                raise HTTPException(401, "ChatGPT session expired; sign in again")
            try:
                metadata = await oauth.chatgpt.load_server_metadata()
                refreshed = await oauth.chatgpt.fetch_access_token(metadata["token_endpoint"],
                    grant_type="refresh_token", refresh_token=token["refresh_token"], resource="https://api.openai.com/v1")
                account["token"] = {**token, **dict(refreshed)}
                save(request, account)
                token = account["token"]
            except Exception:
                raise HTTPException(401, "ChatGPT token renewal failed; sign in again") from None
    return token["access_token"], "chatgpt"


@router.post("/logout")
async def logout(request: Request):
    account = load(request)
    if account and account["provider"] == "chatgpt" and account["token"].get("refresh_token"):
        try:
            metadata = await oauth.chatgpt.load_server_metadata()
            async with httpx.AsyncClient(timeout=15) as client:
                result = await client.post(metadata["revocation_endpoint"], data={
                    "token": account["token"]["refresh_token"], "token_type_hint": "refresh_token", "client_id": CLIENT_ID},
                    auth=(CLIENT_ID, os.getenv("CHATGPT_CLIENT_SECRET", "")) if os.getenv("CHATGPT_CLIENT_SECRET") else None)
                result.raise_for_status()
        except Exception:
            raise HTTPException(502, "ChatGPT revocation failed; retry or disconnect in ChatGPT settings") from None
    with sqlite3.connect(DB_PATH) as db:
        db.execute("DELETE FROM sessions WHERE id = ?", (request.session.get("account", ""),))
    request.session.clear()
    return {"connected": False}
