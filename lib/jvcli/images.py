"""Bounded client image preflight; decoding/readiness remain server responsibilities."""
from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
import re
import stat

from .safety import ProtocolError, private_dir

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_TOTAL = 12 * 1024 * 1024
MAX_IMAGE_REQUEST = 17 * 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024


def image_mime(data: bytes) -> str:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    raise ProtocolError('Only PNG, JPEG and WebP images are supported')


def validate_image(part: dict) -> int:
    if set(part) - {'type', 'image_url', 'detail'}:
        raise ProtocolError('Unsupported image field')
    if part.get('detail', 'auto') not in ('auto', 'high'):
        raise ProtocolError('JV images support auto or high detail only')
    url = part.get('image_url')
    if not isinstance(url, str) or len(url) > 6990508 + 32:
        raise ProtocolError('Invalid or oversized image data URL')
    match = re.fullmatch(r'data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]*={0,2})', url)
    if match is None:
        raise ProtocolError('Images require an inline PNG, JPEG or WebP base64 data URL; paths and remote URLs are unsupported')
    try:
        data = base64.b64decode(match[2], validate=True)
    except (ValueError, binascii.Error):
        raise ProtocolError('Invalid image base64') from None
    if base64.b64encode(data).decode('ascii') != match[2]:
        raise ProtocolError('Image base64 must be canonical')
    if not 0 < len(data) <= MAX_IMAGE_BYTES or len(match[2]) > 6990508:
        raise ProtocolError('Image exceeds the 5 MiB limit')
    if image_mime(data) != match[1]:
        raise ProtocolError('Image MIME does not match its signature')
    return len(data)


def validate_image_results(output) -> None:
    if not isinstance(output, list) or not 1 <= len(output) <= 4:
        raise ProtocolError('Image tool output must contain 1–4 input_image items')
    total = 0
    for part in output:
        if not isinstance(part, dict) or part.get('type') != 'input_image':
            raise ProtocolError('Image tool output accepts input_image items only')
        total += validate_image(part)
    if total > MAX_IMAGE_TOTAL:
        raise ProtocolError('Image tool output exceeds 12 MiB decoded total')


def validate_image_history(inputs) -> None:
    """Apply the server's image count/byte limits across replayed local history."""
    if isinstance(inputs, str):
        return
    if not isinstance(inputs, list):
        raise ProtocolError('Structured input must be text or an item list')
    count, total = 0, 0
    for item in inputs:
        if not isinstance(item, dict):
            raise ProtocolError('Structured input items must be objects')
        groups = []
        if item.get('role') == 'user' and isinstance(item.get('content'), list):
            groups.append([part for part in item['content']
                           if isinstance(part, dict) and part.get('type') == 'input_image'])
        if item.get('type') == 'function_call_output' and isinstance(item.get('output'), list):
            validate_image_results(item['output'])
            groups.append(item['output'])
        for group in groups:
            for part in group:
                total += validate_image(part)
                count += 1
    if count > 4 or total > MAX_IMAGE_TOTAL:
        raise ProtocolError('Structured image history exceeds 4 images or 12 MiB decoded total')


def validate_image_request(body: dict) -> None:
    """Validate complete ordered user input without opening any referenced path."""
    count, total = 0, 0
    metadata = dict(body)
    inputs = body.get('input', [])
    if not isinstance(inputs, list):
        if not isinstance(inputs, str):
            raise ProtocolError('Structured input must be text or an item list')
        inputs = []
    else:
        metadata['input'] = []
    for item in inputs:
        if not isinstance(item, dict):
            raise ProtocolError('Structured input items must be objects')
        copy = dict(item)
        if item.get('type') == 'function_call_output' and isinstance(item.get('output'), list):
            if len(inputs) != 1 or not body.get('previous_response_id'):
                raise ProtocolError('Image tool output must be the sole input with a predecessor')
            validate_image_results(item['output'])
            copy['output'] = []
            for part in item['output']:
                total += validate_image(part)
                count += 1
                copy['output'].append({**part, 'image_url': '<image>'})
        content = item.get('content')
        if isinstance(content, list):
            copy['content'] = []
            for part in content:
                if not isinstance(part, dict):
                    raise ProtocolError('Structured content items must be objects')
                if part.get('type') == 'input_image':
                    if item.get('role') != 'user':
                        raise ProtocolError('JV image content is supported only in user messages')
                    total += validate_image(part)
                    count += 1
                    part = {**part, 'image_url': '<image>'}
                copy['content'].append(part)
        metadata['input'].append(copy)
    if count > 4 or total > MAX_IMAGE_TOTAL:
        raise ProtocolError('Image request exceeds 4 images or 12 MiB decoded total')
    if len(json.dumps(metadata, ensure_ascii=False, separators=(',', ':')).encode()) > MAX_METADATA_BYTES:
        raise ProtocolError('Structured request metadata exceeds the 64 KiB limit')


def snapshot_images(paths, workspace: Path, directory: Path) -> list[Path]:
    """Open beneath the workspace via directory FDs; reject symlinks at every hop.

    Codex receives private immutable snapshots, never a user-controlled path that
    could be swapped after validation. No path from a model request is opened here.
    """
    if len(paths) > 4:
        raise ProtocolError('At most four initial images are supported')
    snapshots, total = [], 0
    for value in paths:
        path = Path(value)
        if path.is_absolute():
            try:
                path = path.relative_to(workspace)
            except ValueError:
                raise ProtocolError('Initial image must be inside the selected workspace') from None
        if not path.parts or '..' in path.parts:
            raise ProtocolError('Initial image must be inside the selected workspace')
        fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in path.parts[:-1]:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            file_fd = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(file_fd, 'rb') as handle:
                meta = os.fstat(handle.fileno())
                if not stat.S_ISREG(meta.st_mode) or not 0 < meta.st_size <= MAX_IMAGE_BYTES:
                    raise ProtocolError('Initial image must be a regular file of at most 5 MiB')
                data = handle.read(MAX_IMAGE_BYTES + 1)
        except OSError:
            raise ProtocolError('Cannot safely read initial image; symlinks are not allowed') from None
        finally:
            os.close(fd)
        total += len(data)
        if len(data) > MAX_IMAGE_BYTES or total > MAX_IMAGE_TOTAL:
            raise ProtocolError('Initial images exceed the decoded size limit')
        mime = image_mime(data)
        private_dir(directory)
        target = directory / (str(len(snapshots)) + '.' + mime.split('/')[1])
        out = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(out, 'wb') as handle:
            handle.write(data)
        snapshots.append(target)
    return snapshots
