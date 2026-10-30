"""Check the Git file list, never crawl local runtime data or print secret values."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIRS = {'.git', '.venv', 'node_modules', '.workbench', '.dev', '.releases', '.runtime', '.suno-cn', '__pycache__', '.pytest_cache', 'dist'}
SECRET = re.compile(r'\b(?:sks_[0-9a-f]{64}|sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|tsk_[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b')
HOME = re.compile(r'(?:[A-Z]:[\\/]+Users[\\/]+[^\\/\s"\']+|(?<![A-Za-z0-9.])/(?:Users|home)/[^/\s"\'#]+)', re.I)
TOKEN = re.compile(r'"(?:access_token|refresh_token|id_token)"\s*:\s*"[^"\s]+"')


def tracked_files():
    result = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, check=True)
    names = result.stdout.decode('utf-8').split('\0')
    return [Path(name) for name in names if name]


def problems(relative, raw):
    issues = []
    if any(part in PRIVATE_DIRS for part in relative.parts) or (relative.name.startswith('.env') and relative.name != '.env.example'):
        issues.append('private or generated path')
    if relative.suffix in ('.db', '.sqlite3', '.key', '.pem') or relative.name in ('auth.json', 'credentials.json'):
        issues.append('credential or database file')
    if len(relative.parts) == 1 and (relative.name in ('packaged.json', 'SHA256SUMS.json') or relative.name.startswith(('ZAOWU', 'Questweft')) and relative.suffix.lower() == '.exe'):
        issues.append('generated Windows distribution file')
    if len(raw) > 5 * 1024 * 1024:
        issues.append('file exceeds 5 MB source limit')
    if b'\x00' not in raw:
        content = raw.decode('utf-8-sig', errors='replace')
        for pattern, label in ((SECRET, 'possible secret'), (HOME, 'personal absolute path'), (TOKEN, 'account token field')):
            if pattern.search(content):
                issues.append(label)
    return issues


def check():
    failures, files = [], tracked_files()
    if not files:
        raise ValueError('No Git files found. Initialize the repository and stage the intended source files first.')
    for relative in files:
        path = ROOT / relative
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            failures.append(f'{relative.as_posix()}: unsupported symlink or outside path')
            continue
        if not path.is_file():
            failures.append(f'{relative.as_posix()}: tracked file missing')
            continue
        failures.extend(f'{relative.as_posix()}: {issue}' for issue in problems(relative, path.read_bytes()))
    if failures:
        raise ValueError('\n'.join(failures))
    return files


if __name__ == '__main__':
    try:
        print(f'Public file checks passed: {len(check())} Git files. Manual review is still required.')
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
