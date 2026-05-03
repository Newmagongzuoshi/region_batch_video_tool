import os
import json
import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from utils.path_utils import resolve_path, ensure_dir
from utils.logger import get_logger

logger = get_logger()

_fernet: Fernet | None = None


def _get_key() -> bytes:
    """Derive a machine-local encryption key. NOT hardcoded."""
    kdf_salt = b"region_batch_video_tool_salt_v1"
    machine_id = os.environ.get("COMPUTERNAME", "default_host").encode()
    user_name = os.environ.get("USERNAME", "default_user").encode()
    material = machine_id + b"|" + user_name

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=kdf_salt,
        iterations=480000,
    )
    import cryptography.hazmat.backends as backends
    key = base64.urlsafe_b64encode(kdf.derive(material))
    return key


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_get_key())
    return _fernet


def encrypt_value(value: str) -> str:
    f = _get_fernet()
    return f.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(encrypted: str) -> str:
    f = _get_fernet()
    return f.decrypt(encrypted.encode("utf-8")).decode("utf-8")


def mask_api_key(key: str) -> str:
    """Mask API key for display: sk-12****cdef"""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * (len(key) - 8) + key[-4:]
