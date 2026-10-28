"""Credentials stay in the local backend; Windows uses the current user's DPAPI."""
import base64
import ctypes
import os
from ctypes import wintypes
from . import store


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(raw, decrypt=False):
    if os.name != 'nt':
        raise ValueError('此版本仅在 Windows 上持久保存密钥；其他平台请使用环境变量')
    buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise ValueError('Windows 凭据保护失败')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


def get_key(provider):
    saved = store.setting('secret_' + provider)
    if saved:
        return crypt(base64.b64decode(saved), decrypt=True).decode()
    return os.environ.get(provider.upper() + '_API_KEY', '')


def save_key(provider, key):
    store.set_setting('secret_' + provider, base64.b64encode(crypt(key.encode())).decode() if key else None)
