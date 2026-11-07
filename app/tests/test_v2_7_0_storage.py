"""CR-046 回归：附件存储抽象（local / SMB 挂载路径）。"""
from __future__ import annotations

import tempfile
import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.services import storage_service


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def h(client):
    r = client.post("/api/auth/login",
                    json={"username": ADMIN_USERNAME, "password": ADMIN_INIT_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_local_save_read_delete():
    with SessionLocal() as db:
        storage_service.save_config(db, {"backend": "local"})
        key = f"tests/{uuid.uuid4().hex}.txt"
        backend, key = storage_service.save_bytes(db, b"hello-storage", key)
        assert backend == "local"
        assert storage_service.read_bytes(db, backend, key) == b"hello-storage"
        storage_service.delete_bytes(db, backend, key)
        with pytest.raises(FileNotFoundError):
            storage_service.read_bytes(db, backend, key)


def test_smb_backend_probe_and_io(tmp_path):
    with SessionLocal() as db:
        storage_service.save_config(db, {"backend": "local"})   # 先确保默认
    try:
        with SessionLocal() as db:
            cfg = storage_service.save_config(db, {"backend": "smb",
                                                   "smb_path": str(tmp_path),
                                                   "prefix": "ctms/"})
            assert cfg["backend"] == "smb" and cfg["writable"] is True
            probe = storage_service.probe(db)
            assert probe["ok"] is True, probe
            key = f"tests/{uuid.uuid4().hex}.pdf"
            backend, key = storage_service.save_bytes(db, b"%PDF-test", key)
            assert backend == "smb"
            assert (tmp_path / "ctms" / key).is_file()
            assert storage_service.read_bytes(db, backend, key) == b"%PDF-test"
    finally:
        with SessionLocal() as db:
            storage_service.save_config(db, {"backend": "local", "smb_path": "", "prefix": ""})


def test_smb_requires_mount_path():
    with SessionLocal() as db:
        with pytest.raises(ValueError):
            storage_service.save_config(db, {"backend": "smb", "smb_path": ""})


def test_api_config_and_probe(client, h, tmp_path):
    r = client.put("/api/system/attachment-storage", headers=h,
                   json={"backend": "smb", "smb_path": str(tmp_path), "prefix": "ctms/"})
    assert r.status_code == 200, r.text
    assert r.json()["backend"] == "smb"
    t = client.post("/api/system/attachment-storage/test", headers=h)
    assert t.status_code == 200 and t.json()["ok"] is True, t.text
    g = client.get("/api/system/attachment-storage", headers=h)
    assert g.json()["backend"] == "smb"
    # 还原 default
    client.put("/api/system/attachment-storage", headers=h,
               json={"backend": "local", "smb_path": "", "prefix": ""})
