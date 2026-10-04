"""Explicit operator-only download. Serving requests never calls this module."""
import json
from pathlib import Path
import tempfile

from .encoder_artifact import artifact_revision

REPOSITORY = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
SOURCE_REVISION = 'e8f8c211226b894fcb81acc59f3b34ba3efd5f42'


def prepare_default_encoder(directory: Path) -> tuple[Path, str]:
    output = directory.resolve() / SOURCE_REVISION
    if output.exists():
        manifest = json.loads((output / 'router-manifest.json').read_text(encoding='utf-8'))
        revision = artifact_revision(output)
        if (manifest.get('repository') != REPOSITORY or manifest.get('source_revision') != SOURCE_REVISION
                or manifest.get('artifact_revision') != revision):
            raise ValueError('Existing encoder artifact failed identity verification; use a new artifact directory.')
        return output, revision
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(REPOSITORY, revision=SOURCE_REVISION, backend='onnx', device='cpu',
        tokenizer_kwargs={'fix_mistral_regex': False},  # Pinned MiniLM is BERT, not Mistral.
        trust_remote_code=False, model_kwargs={'export': False, 'file_name': 'onnx/model.onnx',
                                              'provider': 'CPUExecutionProvider'})
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='prepare-', dir=directory) as temporary:
        staged = Path(temporary) / 'artifact'
        model.save_pretrained(str(staged))
        if not (staged / 'onnx' / 'model.onnx').is_file():
            raise ValueError('Downloaded encoder lacks the required ONNX artifact.')
        revision = artifact_revision(staged)
        (staged / 'router-manifest.json').write_text(json.dumps({
            'repository': REPOSITORY, 'source_revision': SOURCE_REVISION,
            'artifact_revision': revision, 'max_seq_length': model.max_seq_length,
        }), encoding='utf-8')
        # Reserve the destination exclusively; only move into our own new directory.
        output.mkdir(exist_ok=False)
        try:
            for item in staged.iterdir():
                item.rename(output / item.name)
        except Exception:
            # Do not erase a partial artifact. The next run rejects it explicitly.
            raise ValueError('Artifact publication failed; incomplete files were preserved for inspection.') from None
    return output, revision
