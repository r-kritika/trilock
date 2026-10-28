import numpy as np
import pytest

from app.services.templates import TemplateStore


def test_roundtrip_and_encrypted_on_disk(tmp_path):
    s = TemplateStore(tmp_path / "templates", None)
    emb = np.arange(8, dtype=np.float32).reshape(2, 4)
    name = s.save(1, "face", {"embeddings": emb})
    raw = (tmp_path / "templates" / name).read_bytes()
    assert b"PK" not in raw[:4] and b"embeddings" not in raw     # not a plain npz
    assert np.array_equal(s.load(1, "face")["embeddings"], emb)
    assert s.load(1, "voice") is None
    s.delete(1, "face")
    assert s.load(1, "face") is None


def test_wrong_key_cannot_read(tmp_path):
    TemplateStore(tmp_path / "t", None).save(1, "face", {"e": np.ones(3)})
    (tmp_path / "template.key").unlink()
    with pytest.raises(RuntimeError):
        TemplateStore(tmp_path / "t", None).load(1, "face")
