"""Encrypted on-disk storage for biometric templates.

Templates are numpy arrays (embeddings / keypoint descriptors), serialised and encrypted with
Fernet (AES-128-CBC + HMAC). Raw images and audio are never written to disk by the app.
The key comes from TRILOCK_TEMPLATE_KEY or is generated once into data/template.key.
This protects files at rest only; it is not a cancellable / irreversible template scheme.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import numpy as np
from cryptography.fernet import Fernet, InvalidToken


class TemplateStore:
    def __init__(self, root: Path, key: str | None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(self._resolve_key(key))

    def _resolve_key(self, key: str | None) -> bytes:
        if key:
            return key.encode()
        key_path = self.root.parent / "template.key"
        if key_path.exists():
            return key_path.read_bytes().strip()
        new_key = Fernet.generate_key()
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(new_key)
        return new_key

    def _path(self, user_id: int, modality: str) -> Path:
        return self.root / f"user{int(user_id)}_{modality}.tpl"

    def save(self, user_id: int, modality: str, template: dict) -> str:
        buf = io.BytesIO()
        np.savez_compressed(buf, **template)
        path = self._path(user_id, modality)
        path.write_bytes(self._fernet.encrypt(buf.getvalue()))
        return path.name

    def load(self, user_id: int, modality: str) -> dict | None:
        path = self._path(user_id, modality)
        if not path.exists():
            return None
        try:
            plain = self._fernet.decrypt(path.read_bytes())
        except InvalidToken as e:
            raise RuntimeError("template cannot be decrypted; was the template key changed?") from e
        with np.load(io.BytesIO(plain), allow_pickle=False) as z:
            return {k: z[k] for k in z.files}

    def delete(self, user_id: int, modality: str) -> None:
        self._path(user_id, modality).unlink(missing_ok=True)
