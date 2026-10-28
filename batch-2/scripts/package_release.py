"""Package reviewed Git files and the built UI, excluding all local user data."""
import hashlib
import json
import zipfile
from pathlib import Path

from check_release import ROOT, check


def main():
    files = check()
    if not (ROOT / 'dist/index.html').is_file():
        raise ValueError('Build the UI with npm run build before packaging.')
    package = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))
    name = f"{package['name']}-{package['version']}"
    destination = ROOT / '.releases' / (name + '.zip')
    destination.parent.mkdir(exist_ok=True)
    files += [p.relative_to(ROOT) for p in sorted((ROOT / 'dist').rglob('*')) if p.is_file()]
    hashes = {}
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(files):
            path = ROOT / relative
            if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
                raise ValueError('Unsupported release path: ' + relative.as_posix())
            raw = path.read_bytes()
            hashes[relative.as_posix()] = hashlib.sha256(raw).hexdigest()
            archive.writestr(name + '/' + relative.as_posix(), raw)
        archive.writestr(name + '/SHA256SUMS.json', json.dumps(hashes, indent=2) + '\n')
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(digest + '  ' + destination.name + '\n', encoding='utf-8')
    print(f'Release candidate: {destination.name} ({destination.stat().st_size:,} bytes)')
    print('Includes reviewed source and built UI. Runtime dependencies are installed separately.')


if __name__ == '__main__':
    main()
