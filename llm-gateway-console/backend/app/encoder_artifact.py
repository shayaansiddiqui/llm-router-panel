"""Identity includes tokenizer, pooling configuration and ONNX weights."""
from hashlib import sha256
from pathlib import Path


def artifact_revision(directory: Path) -> str:
    digest = sha256()
    files = sorted(path for path in directory.rglob('*') if path.is_file()
                   and path.name != 'router-manifest.json')
    if not files:
        raise ValueError('Empty encoder artifact')
    for path in files:
        if path.is_symlink():
            raise ValueError('Encoder artifacts must not contain symlinks')
        digest.update(path.relative_to(directory).as_posix().encode('utf-8'))
        digest.update(b'\0')
        file_digest = sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                file_digest.update(block)
        digest.update(file_digest.digest())
    return digest.hexdigest()
