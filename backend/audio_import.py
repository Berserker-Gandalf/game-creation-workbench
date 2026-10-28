"""Credential-free public audio retrieval; never an arbitrary URL proxy or converter."""
import asyncio
import ipaddress
import math
import socket
import wave
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from tinytag import TinyTag, TinyTagException

MAX_BYTES = 50 * 1024 ** 2


async def public_target(url):
    if not isinstance(url, str) or len(url) > 16000: raise ValueError('音频地址无效，请重新查询已完成任务')
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError: raise ValueError('音频地址无效') from None
    if p.scheme != 'https' or not p.hostname or p.username or p.password or port not in (None, 443) or p.fragment: raise ValueError('仅接入任务返回的公网HTTPS音频，不使用凭据或跟随跳转')
    try: addresses = await asyncio.to_thread(socket.getaddrinfo, p.hostname, 443, type=socket.SOCK_STREAM)
    except OSError: raise ValueError('音频服务器无法解析，请稍后重新查询') from None
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses): raise ValueError('不允许从本机或私有网络下载音频')
    return p.hostname, addresses[0][4][0]


async def download(url, path):
    host, address = await public_target(url)
    # Pin the checked public IP while keeping the original TLS name and HTTP host.
    target = httpx.URL(url).copy_with(host=address)
    size = 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15), trust_env=False, follow_redirects=False) as client:
            async with client.stream('GET', target, headers={'Host': host, 'Accept': 'audio/mpeg,audio/wav,application/octet-stream', 'Accept-Encoding': 'identity'}, extensions={'sni_hostname': host}) as response:
                if response.status_code != 200: raise ValueError('音频下载未成功或发生跳转；请重新查询结果，不会重新生成')
                mime = response.headers.get('content-type', '').split(';')[0].lower().strip()
                if mime not in ('audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/wave', 'application/octet-stream'): raise ValueError('服务返回的文件类型不是支持的音频')
                if response.headers.get('content-encoding', 'identity').lower() not in ('', 'identity'): raise ValueError('不接入压缩响应体，请重新查询音频直链')
                if int(response.headers.get('content-length', '0')) > MAX_BYTES: raise ValueError('音频超过50 MiB接入上限')
                with Path(path).open('xb') as f:
                    async for chunk in response.aiter_bytes(65536):
                        size += len(chunk)
                        if size > MAX_BYTES: raise ValueError('音频超过50 MiB接入上限')
                        f.write(chunk)
        if not size: raise ValueError('服务返回空文件')
    except httpx.HTTPError: raise ValueError('音频连接中断；未登记部分文件，可重新查询或下载') from None


def verify(path):
    path = Path(path)
    if not 0 < path.stat().st_size <= MAX_BYTES: raise ValueError('音频文件体积无效')
    with path.open('rb') as f: header = f.read(12)
    if header.startswith(b'RIFF') and header[8:12] == b'WAVE':
        suffix, mime = '.wav', 'audio/wav'
        try:
            with wave.open(str(path), 'rb') as audio:
                frames = audio.getnframes(); expected = frames * audio.getnchannels() * audio.getsampwidth()
                total = 0
                while chunk := audio.readframes(65536): total += len(chunk)
                if total != expected or audio.getcomptype() != 'NONE': raise ValueError('WAV音频数据不完整或不是PCM')
                channels, rate = audio.getnchannels(), audio.getframerate()
                if not rate: raise ValueError('WAV采样率无效')
                duration = frames / rate
        except (wave.Error, EOFError): raise ValueError('文件不是完整的PCM WAV音频') from None
    elif header.startswith(b'ID3') or len(header) >= 2 and header[0] == 255 and header[1] & 224 == 224:
        suffix, mime = '.mp3', 'audio/mpeg'
        try:
            with path.open('rb') as f: tag = TinyTag.get(file_obj=f, tags=False, duration=True, image=False)
            duration, channels, rate = tag.duration, tag.channels, tag.samplerate
        except (TinyTagException, ValueError, OSError): raise ValueError('无法识别有效MP3音频流') from None
    else: raise ValueError('仅接入可识别的MP3或PCM WAV；不自动提交收费格式转换')
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 0 < duration <= 3600 or channels not in (1, 2) or not rate or not 8000 <= rate <= 192000: raise ValueError('音频时长、声道或采样率不符合接入范围')
    return {'suffix': suffix, 'mime': mime, 'duration': duration, 'channels': channels, 'sample_rate': rate}
