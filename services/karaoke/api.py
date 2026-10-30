"""Score-only API. Song preparation is performed by the local CLI."""

import asyncio
from contextlib import asynccontextmanager
import hmac
import logging
import re
from types import SimpleNamespace
import uuid

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException

from services.karaoke import __version__
from services.karaoke.config import Settings
from services.karaoke.errors import ServiceError
from services.karaoke.resources import verify_memory_limit
from services.karaoke.runtime import Admission, Workspaces
from services.karaoke.scoring import (
    EXTRACTOR_VERSION, SCORING_VERSION, RecordingFeatures, Timing,
    read_reference, score_features, score_recording,
)


logger = logging.getLogger(__name__)
PROCESSING = {"/v1/score", "/v1/score/features"}
REQUEST_ID = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
bearer = HTTPBearer(auto_error=False)


def failure(code, message, status, request_id):
    return JSONResponse({"error": {"code": code, "message": message}, "request_id": request_id}, status_code=status)


class RequestPolicy:
    def __init__(self, app, settings, state):
        self.app, self.settings, self.state = app, settings, state

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")
        scope["karaoke.request_id"] = supplied if REQUEST_ID.fullmatch(supplied) else uuid.uuid4().hex
        request_id = scope["karaoke.request_id"]
        path = scope["path"]
        if path.startswith("/v1/"):
            authorization = headers.get(b"authorization", b"")
            expected = ("Bearer " + self.settings.api_key).encode()
            if not hmac.compare_digest(authorization, expected):
                return await failure("UNAUTHORIZED", "Valid backend credentials are required", 401, request_id)(scope, receive, send)
        lease = None
        if scope["method"] == "POST" and path in PROCESSING:
            if not self.state.ready:
                return await failure("SERVICE_NOT_READY", "The scoring service is not ready", 503, request_id)(scope, receive, send)
            try:
                declared = int(headers.get(b"content-length", b"0"))
                if declared < 0:
                    raise ValueError()
            except ValueError:
                return await failure("INVALID_LENGTH", "Invalid content length", 400, request_id)(scope, receive, send)
            if declared > self.settings.max_request_bytes:
                return await failure("REQUEST_TOO_LARGE", "Request exceeds its size budget", 413, request_id)(scope, receive, send)
            lease = self.state.admission.acquire()
            if lease is None:
                response = failure("SERVICE_BUSY", "One audio task is already in progress; retry from your backend", 503, request_id)
                response.headers["Retry-After"] = "5"
                return await response(scope, receive, send)
            scope["karaoke.lease"] = lease
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.settings.max_request_bytes:
                    # The multipart parser catches this type and closes spooled uploads.
                    raise MultiPartException("KARAOKE_BODY_LIMIT")
            return message

        async def tagged_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []),
                                      (b"x-request-id", scope["karaoke.request_id"].encode()),
                                      (b"cache-control", b"no-store")]
            await send(message)

        try:
            await self.app(scope, bounded_receive, tagged_send)
        finally:
            if lease:
                lease.request_finished()  # Work/cleanup remains leased until a disconnected CPU task finishes.


def multipart_schema(files: list[str], fields: dict | None = None) -> dict:
    properties = {name: {"type": "string", "format": "binary"} for name in files}
    properties.update({"request_id": {"type": "string"}, **(fields or {})})
    return {"requestBody": {"required": True, "content": {"multipart/form-data": {
        "schema": {"type": "object", "required": files, "properties": properties}}}}}


def create_app(settings: Settings | None = None, *, engine=None) -> FastAPI:
    settings = settings or Settings.from_env()
    state = SimpleNamespace(ready=False, admission=Admission(), workspaces=None, resource_policy=None)

    @asynccontextmanager
    async def lifespan(app):
        state.resource_policy = ({"test_mode": True} if engine is not None else verify_memory_limit(settings.memory_percent))
        state.workspaces = Workspaces(settings.temp_dir)
        try:
            state.ready = True
            yield
        finally:
            state.ready = False
            if state.admission.tasks:
                await asyncio.gather(*list(state.admission.tasks), return_exceptions=True)
            state.workspaces.close()

    app = FastAPI(title="Karaoke Scoring API", version=__version__, lifespan=lifespan,
                  description="Scores a completed singing recording or incremental pitch features against a "
                              "precomputed pitch reference. Song separation and reference generation run "
                              "locally before playback.")
    app.state.karaoke = state
    app.add_middleware(RequestPolicy, settings=settings, state=state)

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        return failure(exc.code, exc.message, exc.status_code, request.scope.get("karaoke.request_id"))

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        oversized = "KARAOKE_BODY_LIMIT" in str(exc.detail)
        return failure("REQUEST_TOO_LARGE" if oversized else "INVALID_REQUEST",
                       "Request exceeds its size budget" if oversized else "Invalid request or multipart data",
                       413 if oversized else exc.status_code, request.scope.get("karaoke.request_id"))

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        logger.exception("Audio request failed: %s", request.scope.get("karaoke.request_id"))
        return failure("INTERNAL_ERROR", "Audio processing failed; correlate request_id with server logs", 500,
                       request.scope.get("karaoke.request_id"))

    def workspace(request):
        lease = request.scope["karaoke.lease"]
        lease.workspace = state.workspaces.create()
        return lease, lease.workspace

    def text_field(form, name, default=""):
        values = form.getlist(name)
        if len(values) > 1 or (values and not isinstance(values[0], str)):
            raise ServiceError("INVALID_FIELD", f"Invalid {name} field")
        value = values[0] if values else default
        if len(value) > 8192:
            raise ServiceError("INVALID_FIELD", f"Field {name} is too long")
        return value

    def request_identity(request, form):
        value = text_field(form, "request_id", request.scope["karaoke.request_id"])
        if not REQUEST_ID.fullmatch(value):
            raise ServiceError("INVALID_REQUEST_ID", "request_id must be 1-96 ASCII letters/digits/._-")
        request.scope["karaoke.request_id"] = value
        return value

    async def save_upload(form, name, destination, max_bytes):
        values = form.getlist(name)
        if len(values) != 1 or not isinstance(values[0], UploadFile):
            raise ServiceError("MISSING_FILE", f"One {name} file is required")
        total = 0
        with destination.open("wb") as output:
            while block := await values[0].read(65536):
                total += len(block)
                if total > max_bytes:
                    raise ServiceError("FILE_TOO_LARGE", f"{name} exceeds its size budget", 413)
                output.write(block)
        if total == 0:
            raise ServiceError("EMPTY_FILE", f"{name} is empty")

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready():
        return JSONResponse({"status": "ready" if state.ready else "not_ready",
                             "device": "cpu", "component": "score-only"},
                            status_code=200 if state.ready else 503)

    @app.get("/v1/info", dependencies=[Depends(bearer)])
    async def info():
        return {"service_version": __version__, "service_mode": "score-only",
                "environment": settings.environment, "device": "cpu",
                "scoring_method": "pYIN references or browser YIN pitch features with experimental "
                                  "30/20/50 pitch/rhythm/coverage scoring",
                "extractor_version": EXTRACTOR_VERSION, "scoring_version": SCORING_VERSION,
                "memory_policy": state.resource_policy,
                "limits": {"max_request_bytes": settings.max_request_bytes,
                           "max_reference_bytes": settings.max_reference_bytes,
                           "max_duration_seconds": settings.max_duration_seconds, "audio_concurrency": 1}}

    @app.post("/v1/score", dependencies=[Depends(bearer)],
              openapi_extra=multipart_schema(["recording", "reference"], {"timing": {"type": "string", "default": "{}"}}))
    async def score(request: Request):
        lease, work = workspace(request)
        async with request.form(max_files=2, max_fields=3, max_part_size=16384) as form:
            request_id = request_identity(request, form)
            try:
                timing = Timing.model_validate_json(text_field(form, "timing", "{}"))
            except ValidationError as exc:
                raise ServiceError("INVALID_TIMING", "Invalid recording/playback timing metadata") from exc
            recording, reference = work / "recording.upload", work / "reference.json"
            await save_upload(form, "recording", recording, settings.max_request_bytes)
            await save_upload(form, "reference", reference, settings.max_reference_bytes)
            return await lease.compute(lambda: score_recording(recording, reference, work, settings, timing, request_id))

    @app.post("/v1/score/features", dependencies=[Depends(bearer)],
              openapi_extra=multipart_schema(["features", "reference"], {"timing": {"type": "string", "default": "{}"}}))
    async def score_feature_request(request: Request):
        lease, work = workspace(request)
        async with request.form(max_files=2, max_fields=1, max_part_size=settings.max_request_bytes) as form:
            request_id = request_identity(request, form)
            try:
                timing = Timing.model_validate_json(text_field(form, "timing", "{}"))
            except ValidationError as exc:
                raise ServiceError("INVALID_TIMING", "Invalid recording/playback timing metadata") from exc
            features_path, reference_path = work / "features.json", work / "reference.json"
            await save_upload(form, "features", features_path, settings.max_request_bytes)
            await save_upload(form, "reference", reference_path, settings.max_reference_bytes)
            try:
                features = RecordingFeatures.model_validate_json(features_path.read_bytes())
                reference = read_reference(reference_path, settings)
            except ValidationError as exc:
                raise ServiceError("INVALID_FEATURES", "Recording pitch features are invalid") from exc
            return await lease.compute(
                lambda: score_features(reference, features.model_dump(), timing, request_id)
            )

    return app
