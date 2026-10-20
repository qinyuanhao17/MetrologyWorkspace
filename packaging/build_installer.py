"""Wrap a hash-verified portable ZIP; do not rebuild application code."""
import argparse
import hashlib
import re
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import zipfile

PORTABLE_SHA256 = 'a3599de63275f07209e746b34c7b2959d3c8c6d2f1630e8b4a68b7e6c1e9aac1'


def build(archive, compiler, output, *, version='4.0.0', portable_sha256=PORTABLE_SHA256):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('An explicit numeric application version is required.')
    if not re.fullmatch(r'[0-9a-fA-F]{64}', portable_sha256):
        raise ValueError('An explicit portable SHA-256 is required.')
    archive, compiler, output = map(lambda p: Path(p).resolve(), (archive, compiler, output))
    if hashlib.sha256(archive.read_bytes()).hexdigest() != portable_sha256.lower():
        raise ValueError('Portable ZIP does not match the verified SHA-256.')
    if output.exists():
        raise FileExistsError(output)
    with tempfile.TemporaryDirectory(prefix='installer-build-', dir=archive.parent) as directory:
        scratch = Path(directory)
        with zipfile.ZipFile(archive) as zipped:
            members = zipped.infolist()
            for member in members:
                path = PurePosixPath(member.filename)
                if path.is_absolute() or '..' in path.parts or path.parts[0] != 'MetrologyWorkspace':
                    raise ValueError('Unsafe portable ZIP entry.')
            zipped.extractall(scratch)
        payload = scratch / 'MetrologyWorkspace'
        files = sorted(path.relative_to(payload) for path in payload.rglob('*') if path.is_file())
        forbidden = {'settings.yaml', 'reminders.sqlite3'}
        if any(path.name in forbidden or path.suffix.lower() in ('.wkb', '.mwkb', '.log') for path in files):
            raise ValueError('User data may not be distributed in an installer.')
        if (payload / 'VERSION').read_text(encoding='utf-8').strip() != version:
            raise ValueError(f'Payload version is not {version}.')
        def quote(path):
            value = str(path).replace('$', '$$').replace('"', '$\\"')
            return f'"$INSTDIR\\{value}"'
        lines = ['; Generated exact-file uninstall manifest.']
        lines.extend('Delete ' + quote(path) for path in files)
        directories = {parent for path in files for parent in path.parents if str(parent) != '.'}
        lines.extend('RMDir ' + quote(path) for path in sorted(directories, key=lambda p: len(p.parts), reverse=True))
        manifest = scratch / 'uninstall-files.nsh'
        manifest.write_text('\n'.join(lines), encoding='utf-8-sig')
        subprocess.run([str(compiler), '/V2', f'/DPAYLOAD={payload}', f'/DOUTPUT={output}',
                        f'/DAPP_VERSION={version}', f'/DMANIFEST={manifest}',
                        str(Path(__file__).with_name('windows-installer.nsi'))], check=True)
    print(f'Installer: {output}')
    print(f'Bytes: {output.stat().st_size}')
    print(f'SHA256: {hashlib.sha256(output.read_bytes()).hexdigest()}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--portable-zip', required=True)
    parser.add_argument('--compiler', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--version', default='4.0.0')
    parser.add_argument('--portable-sha256', default=PORTABLE_SHA256)
    args = parser.parse_args()
    build(args.portable_zip, args.compiler, args.output,
          version=args.version, portable_sha256=args.portable_sha256)
