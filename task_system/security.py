"""Enforce API access, shared quotas, and bounded request bodies before routing."""

from hmac import compare_digest

from fastapi import HTTPException
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from task_system.config import Settings

MAX_BODY_BYTES = 2 * 1024 * 1024
UNSAFE = frozenset(("POST", "PUT", "PATCH", "DELETE"))
WINDOW_MS = 60_000
COUNT_REQUEST = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
return {count, redis.call('PTTL', KEYS[1])}
"""


class APIProtection:
    def __init__(self, app: ASGIApp, *, settings: Settings, limiter: Redis | None):
        self.app = app
        self.limiter = limiter
        self.token = settings.api_token.get_secret_value().encode() if settings.api_token else None
        self.origin = settings.public_origin
        self.read_limit = settings.read_rate_per_minute
        self.write_limit = settings.write_rate_per_minute
        self.key_prefix = f"{settings.redis_stream}:http-quota"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (scope["method"] == "GET" and scope["path"] == "/healthz"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)

        async def send_private(message: Message) -> None:
            if self.token is not None and message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "private, no-store"
            await send(message)

        rejection = await self.check_request(headers, scope["method"])
        if rejection is not None:
            await rejection(scope, receive, send_private)
            return

        received = 0

        async def receive_bounded() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Request body exceeds 2 MiB.")
            return message

        await self.app(scope, receive_bounded, send_private)

    async def check_request(self, headers: Headers, method: str) -> JSONResponse | None:
        if self.token is not None:
            scheme, _, credential = headers.get("authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not compare_digest(credential.encode(), self.token):
                return JSONResponse(
                    {"detail": "API authentication required."}, status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )

        write = method in UNSAFE
        origin = headers.get("origin")
        if write and self.origin and origin is not None and origin != self.origin:
            return JSONResponse({"detail": "Request origin is not allowed."}, status_code=403)

        length = headers.get("content-length", "").lstrip("0")
        if length.isdecimal() and (len(length) > 10 or int(length) > MAX_BODY_BYTES):
            return JSONResponse({"detail": "Request body exceeds 2 MiB."}, status_code=413)

        limit = self.write_limit if write else self.read_limit
        if limit and self.limiter is not None:
            key = f"{self.key_prefix}:{'write' if write else 'read'}"
            try:
                used, remaining = await self.limiter.eval(COUNT_REQUEST, 1, key, WINDOW_MS)
            except RedisError:
                return JSONResponse(
                    {"detail": "API rate limiting is temporarily unavailable."}, status_code=503,
                    headers={"Retry-After": "5"},
                )
            if used > limit:
                return JSONResponse(
                    {"detail": "API rate limit reached."}, status_code=429,
                    headers={"Retry-After": str(max(1, (remaining + 999) // 1000))},
                )
        return None
