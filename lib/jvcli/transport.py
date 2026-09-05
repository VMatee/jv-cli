"""JV username/password and jobs protocol. POSTs are never auto-retried."""
from __future__ import annotations

import email.utils
import http.client
import ipaddress
import json
import math
import mimetypes
import os
import re
import secrets
import socket
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .safety import (Cancelled, JvError, SubmissionUncertain, no_symlink_path,
                     positive_number, private_dir, strict_json)

DEFAULT_BASE_URL = "https://ai.openjvspace.com"
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_FILES = 10
PRODUCT_VERSION = (Path(__file__).resolve().parents[2] / "VERSION").read_text(encoding="utf-8").strip()
STATUSES = {"queued", "dispatching", "waiting_for_provider", "running", "waiting_for_auth", "succeeded", "failed"}
NETWORK_ERRORS = (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout, http.client.HTTPException)


class HttpError(JvError):
    def __init__(self, operation: str, status: int, retry_after: float = 0):
        detail = {401: "Sign in again; the credentials or token were rejected.",
                  403: "Access denied.", 404: "The job or conversation is unavailable to this account.",
                  409: "The conversation may already have an unfinished turn.",
                  413: "The request exceeds the server limit.",
                  429: "Rate limited; wait before submitting another request."}.get(status, "")
        super().__init__(f"{operation}: HTTP {status}. {detail}".strip())
        self.status = status
        self.retry_after = retry_after
        self.retryable = status in {408, 409, 429, 500, 502, 503, 504}


class NetworkError(JvError):
    retryable = True
    retry_after = 0.0


def _validate_id(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value))


def validate_base_url(value: str) -> str:
    if not isinstance(value, str):
        raise JvError("JV API base URL must be a string")
    value = value.strip()
    if not value or any(ch.isspace() or ord(ch) < 32 for ch in value) or "\\" in value:
        raise JvError("Invalid JV API base URL")
    try:
        parsed = urllib.parse.urlsplit(value)
        host, port = parsed.hostname, parsed.port
        if (not host or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError()
        loopback = host == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError()
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
        if ":" not in host:
            host = host.encode("idna").decode("ascii")
            if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
                raise ValueError()
        host = f"[{host}]" if ":" in host else host
        return f"{parsed.scheme}://{host}" + (f":{port}" if port is not None else "")
    except (ValueError, UnicodeError):
        raise JvError("Use an HTTPS API origin without credentials/path/query; HTTP is allowed only on loopback") from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _parse_retry_after(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        if value.strip().isdigit():
            delay = float(value.strip())
        else:
            date = email.utils.parsedate_to_datetime(value)
            delay = date.timestamp() - time.time()
        return max(0.0, delay) if math.isfinite(delay) else 86400.0
    except (ValueError, TypeError, OverflowError):
        return 0.0


@dataclass
class JvClientConfig:
    base_url: str = DEFAULT_BASE_URL
    request_timeout: float = 30.0
    poll_interval: float = 2.0
    wait_timeout: float = 3600.0
    max_poll_errors: int = 8
    temp_dir: Path | None = None

    def __post_init__(self):
        self.base_url = validate_base_url(self.base_url)
        for key in ("request_timeout", "poll_interval", "wait_timeout"):
            setattr(self, key, positive_number(getattr(self, key), key))
        if isinstance(self.max_poll_errors, bool) or not isinstance(self.max_poll_errors, int) or not 1 <= self.max_poll_errors <= 20:
            raise JvError("max_poll_errors must be between 1 and 20")


class JvApiClient:
    def __init__(self, config: JvClientConfig):
        self.config = config
        self.base_url = config.base_url
        self._token: str | None = None
        # No ambient proxy settings: never send credentials via an unexpected proxy.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    @property
    def authenticated(self) -> bool:
        return self._token is not None

    def _headers(self, authenticated: bool = False) -> dict[str, str]:
        headers = {"Accept": "application/json", "X-JV-CSRF": "1", "User-Agent": f"JV-CLI/{PRODUCT_VERSION}"}
        if authenticated:
            if not self._token:
                raise JvError("Not signed in")
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _open(self, request, timeout=None):
        return self._opener.open(request, timeout=self.config.request_timeout if timeout is None else timeout)

    def _read_json(self, response):
        body = response.read(MAX_JSON_BYTES + 1)
        if len(body) > MAX_JSON_BYTES:
            raise JvError("JV API returned an oversized response")
        try:
            payload = strict_json(body)
        except (ValueError, UnicodeError, RecursionError):
            raise JvError("JV API returned malformed JSON") from None
        if not isinstance(payload, dict):
            raise JvError("JV API returned an unexpected JSON value")
        return payload

    @staticmethod
    def _http_error(operation, exc):
        error = HttpError(operation, exc.code, _parse_retry_after(exc.headers.get("Retry-After")))
        exc.close()
        return error

    def login(self, username: str, password: str) -> None:
        if self.authenticated:
            raise JvError("Already signed in")
        if not isinstance(username, str) or not username.strip() or not password:
            raise JvError("Username and password are required")
        if len(username) > 256 or len(password) > 16384 or any(ord(c) < 32 for c in username):
            raise JvError("Invalid credential format")
        body = json.dumps({"username": username, "password": password, "remember_me": False}).encode()
        request = urllib.request.Request(self.base_url + "/v1/auth/login", data=body,
                    headers={**self._headers(), "Content-Type": "application/json"}, method="POST")
        try:
            with self._open(request) as response:
                if response.status != 200:
                    raise HttpError("Sign-in", response.status)
                payload = self._read_json(response)
        except urllib.error.HTTPError as exc:
            raise self._http_error("Sign-in", exc) from None
        except NETWORK_ERRORS:
            raise NetworkError("Could not reach the JV sign-in endpoint (network or TLS error)") from None
        token = payload.get("access_token")
        if not isinstance(token, str) or not 1 <= len(token) <= 16384 or not all(33 <= ord(c) <= 126 for c in token):
            raise JvError("JV sign-in returned an invalid token")
        self._token = token

    def logout(self) -> None:
        if not self.authenticated:
            return
        headers = self._headers(True)
        self._token = None
        request = urllib.request.Request(self.base_url + "/v1/auth/logout", data=b"", headers=headers, method="POST")
        try:
            with self._open(request, min(self.config.request_timeout, 5.0)) as response:
                if response.status != 204:
                    raise JvError("Could not confirm token revocation")
        except urllib.error.HTTPError as exc:
            exc.close()
            raise JvError("Could not confirm token revocation") from None
        except NETWORK_ERRORS:
            raise JvError("Could not confirm token revocation") from None

    @staticmethod
    def _validate_job(job: dict[str, Any]) -> None:
        if not _validate_id(job.get("id")) or not _validate_id(job.get("conversation_id")):
            raise JvError("JV API returned an invalid job or conversation ID")
        if not isinstance(job.get("status"), str) or job.get("status") not in STATUSES:
            raise JvError("JV API returned an unsupported job status")

    def submit_job(self, text: str, conversation_id: str | None = None, file_paths=()) -> dict:
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 100 * 1024:
            raise JvError("Job text must be nonempty and at most 100 KiB")
        if conversation_id is not None and not _validate_id(conversation_id):
            raise JvError("Invalid conversation ID")
        headers = self._headers(True)
        paths = list(file_paths)
        if len(paths) > MAX_FILES:
            raise JvError("At most 10 attachments are allowed")
        if self.config.temp_dir:
            private_dir(self.config.temp_dir)
        boundary = "----jvcli-" + secrets.token_hex(16)
        # Disk spool keeps large attachments out of memory, within JV CLI-owned state.
        with tempfile.TemporaryFile(dir=self.config.temp_dir) as spool:
            def field(name, value):
                spool.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
                spool.write(value.encode())
                spool.write(b"\r\n")
            field("text", text)
            if conversation_id:
                field("conversation_id", conversation_id)
            total = 0
            for index, path in enumerate(paths):
                path = no_symlink_path(Path(path))
                try:
                    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    with os.fdopen(fd, "rb") as source:
                        meta = os.fstat(source.fileno())
                        if not stat.S_ISREG(meta.st_mode) or not 0 <= meta.st_size <= MAX_FILE_BYTES:
                            raise JvError("Attachment must be a regular file no larger than 25 MiB")
                        total += meta.st_size
                        if total > MAX_TOTAL_BYTES:
                            raise JvError("Attachments exceed 100 MiB")
                        name = re.sub(r"[^A-Za-z0-9._-]", "_", path.name)[:180] or f"file-{index}"
                        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
                        spool.write((f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
                                     f'Content-Type: {mime}\r\n\r\n').encode())
                        copied = 0
                        while True:
                            chunk = source.read(65536)
                            if not chunk:
                                break
                            copied += len(chunk)
                            if copied > meta.st_size:
                                raise JvError("Attachment changed during upload preparation")
                            spool.write(chunk)
                        if copied != meta.st_size:
                            raise JvError("Attachment changed during upload preparation")
                        spool.write(b"\r\n")
                except OSError:
                    raise JvError(f"Cannot read attachment: {path.name}") from None
            spool.write(f"--{boundary}--\r\n".encode())
            headers.update({"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(spool.tell())})
            spool.seek(0)
            request = urllib.request.Request(self.base_url + "/v1/jobs", data=spool, headers=headers, method="POST")
            try:
                with self._open(request) as response:
                    if response.status != 202:
                        raise SubmissionUncertain("Job submission outcome uncertain; do not automatically repeat the task")
                    try:
                        payload = self._read_json(response)
                        self._validate_job(payload)
                        if conversation_id and payload["conversation_id"] != conversation_id:
                            raise JvError("Mismatched conversation")
                    except JvError:
                        raise SubmissionUncertain("HTTP 202 received but job metadata was invalid; the job may already exist. Do not repeat automatically") from None
            except urllib.error.HTTPError as exc:
                error = self._http_error("Job submission", exc)
                if 400 <= error.status < 500 and error.status != 408:
                    raise error from None
                raise SubmissionUncertain("Job submission outcome uncertain; the job may already exist. Do not repeat automatically") from None
            except NETWORK_ERRORS:
                raise SubmissionUncertain("Job submission connection failed; the job may already exist. Do not repeat automatically") from None
        return payload

    def get_job(self, job_id: str, timeout=None) -> dict:
        if not _validate_id(job_id):
            raise JvError("Invalid job ID")
        request = urllib.request.Request(self.base_url + f"/v1/jobs/{job_id}", headers=self._headers(True))
        try:
            with self._open(request, timeout) as response:
                if response.status != 200:
                    raise HttpError("Polling", response.status)
                payload = self._read_json(response)
        except urllib.error.HTTPError as exc:
            raise self._http_error("Polling", exc) from None
        except NETWORK_ERRORS:
            raise NetworkError("JV polling network request failed") from None
        self._validate_job(payload)
        if payload["id"] != job_id:
            raise JvError("JV API returned a mismatched job ID")
        return payload

    def wait_for_job(self, job_id: str, *, cancel: threading.Event | None = None,
                     progress: Callable[[dict], None] | None = None, conversation_id=None) -> dict:
        cancel = cancel if cancel is not None else threading.Event()
        deadline = time.monotonic() + self.config.wait_timeout
        errors = 0
        while True:
            if cancel.is_set():
                raise Cancelled(f"Stopped waiting for {job_id}; the remote job is not cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise JvError(f"Timed out waiting for {job_id}; the remote job is not cancelled. Use jvcli job {job_id}")
            try:
                job = self.get_job(job_id, timeout=min(remaining, self.config.request_timeout))
                if conversation_id is not None and job["conversation_id"] != conversation_id:
                    raise JvError("JV API changed the conversation ID")
                conversation_id = job["conversation_id"]
                errors = 0
                if progress:
                    progress(job)
                if job["status"] in {"succeeded", "failed"}:
                    return job
                delay = self.config.poll_interval
            except JvError as exc:
                errors += 1
                if not getattr(exc, "retryable", False) or errors >= self.config.max_poll_errors:
                    raise
                delay = max(min(30.0, self.config.poll_interval * 2 ** min(errors - 1, 5)), getattr(exc, "retry_after", 0.0))
            cancel.wait(min(delay, max(0, deadline - time.monotonic())))

    def download_response_files(self, job: dict, destination: Path) -> list[Path]:
        self._validate_job(job)
        if job["status"] != "succeeded":
            raise JvError("Generated files require a succeeded job")
        response = job.get("response") or {}
        files = response.get("files", []) if isinstance(response, dict) else None
        if not isinstance(files, list) or len(files) > MAX_FILES:
            raise JvError("Invalid generated-file manifest")
        manifest = []
        total = 0
        prefix = f'/v1/jobs/{job["id"]}/response-files/'
        for index, item in enumerate(files):
            if not isinstance(item, dict):
                raise JvError("Invalid generated-file entry")
            url, size = item.get("url"), item.get("size_bytes")
            if not isinstance(url, str) or not url.startswith(prefix) or not _validate_id(url[len(prefix):]):
                raise JvError("Generated-file URL must point to this job on the same origin")
            if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_FILE_BYTES:
                raise JvError("Invalid generated-file size")
            total += size
            if total > MAX_TOTAL_BYTES:
                raise JvError("Generated files exceed 100 MiB")
            name = item.get("name")
            name = re.sub(r"[^A-Za-z0-9._ -]", "_", str(name or ""))[:150].strip(" .") or f"output-{index+1}"
            manifest.append((url, size, name))
        if not manifest:
            return []
        destination = no_symlink_path(destination)
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not destination.is_dir():
            raise JvError("Download destination is not a directory")
        downloaded = []
        # Directory descriptor prevents path replacement from redirecting writes.
        dfd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for url, size, name in manifest:
                part = ".jv-download-" + secrets.token_hex(16) + ".part"
                request = urllib.request.Request(self.base_url + url, headers={**self._headers(True), "Accept": "*/*", "Accept-Encoding": "identity"})
                try:
                    with self._open(request) as response:
                        if response.status != 200:
                            raise HttpError("Download", response.status)
                        length = response.headers.get("Content-Length")
                        if length is not None and (not length.isdigit() or int(length) != size):
                            raise JvError("Generated-file length does not match the manifest")
                        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
                        with os.fdopen(fd, "wb") as out:
                            written = 0
                            while True:
                                chunk = response.read(min(65536, size - written + 1))
                                if not chunk:
                                    break
                                written += len(chunk)
                                if written > size:
                                    raise JvError("Generated file exceeds declared size")
                                out.write(chunk)
                            if written != size:
                                raise JvError("Generated file is incomplete")
                            out.flush()
                            os.fsync(out.fileno())
                    for n in range(1000):
                        candidate = name if n == 0 else f"{Path(name).stem}-{n}{Path(name).suffix}"
                        try:
                            os.link(part, candidate, src_dir_fd=dfd, dst_dir_fd=dfd, follow_symlinks=False)
                            downloaded.append(destination / candidate)
                            break
                        except FileExistsError:
                            continue
                    else:
                        raise JvError("Cannot allocate a unique generated-file name")
                except urllib.error.HTTPError as exc:
                    raise self._http_error("Download", exc) from None
                except NETWORK_ERRORS:
                    raise NetworkError("Generated-file download failed") from None
                finally:
                    try:
                        os.unlink(part, dir_fd=dfd)
                    except FileNotFoundError:
                        pass
        finally:
            os.close(dfd)
        return downloaded
