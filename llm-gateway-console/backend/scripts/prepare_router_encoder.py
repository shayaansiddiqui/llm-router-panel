"""Operator-only artifact export. Never invoked by gateway startup/inference."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.encoder_artifact import artifact_revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True, help='Trusted SentenceTransformer repository')
    parser.add_argument('--revision', required=True, help='Immutable 40-character repository commit SHA')
    parser.add_argument('--output', type=Path, required=True, help='New local artifact directory; never overwritten')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        parser.error('--revision must be an immutable commit SHA, not main/latest')
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error('--output already exists; use a new revision-specific directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(args.repository, revision=args.revision, backend='onnx',
                                device='cpu', trust_remote_code=False,
                                model_kwargs={'export': True, 'provider': 'CPUExecutionProvider'})
    with tempfile.TemporaryDirectory(prefix='gsai-encoder-', dir=output.parent) as temporary:
        staged = Path(temporary) / 'artifact'
        model.save_pretrained(str(staged))
        if not (staged / 'onnx' / 'model.onnx').is_file():
            raise RuntimeError('Export did not produce onnx/model.onnx; artifact was not published')
        revision = artifact_revision(staged)
        manifest = {'repository': args.repository, 'source_revision': args.revision,
                    'artifact_revision': revision, 'max_seq_length': model.max_seq_length}
        (staged / 'router-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        # Recheck immediately before publishing. No existing directory is replaced.
        if output.exists():
            raise RuntimeError('Output appeared during export; refusing to replace it')
        os.rename(staged, output)
    print(f'ROUTER_ENCODER_PATH={output}')
    print(f'ROUTER_ENCODER_REVISION={revision}')


if __name__ == '__main__':
    main()
