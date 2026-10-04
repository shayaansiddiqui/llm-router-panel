"""Advanced operator entry point; normal servers prepare automatically."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings
from app.preparation import prepare
from app.learned_router import run_predictor_preparation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider-id', type=int)
    parser.add_argument('--allow-remote', action='store_true', help='Explicitly allow HTTPS Ollama nodes outside this computer')
    parser.add_argument('--automatic', action='store_true', help='Server-managed preparation of missing/stale local models without prompting')
    parser.add_argument('--controller-owner', help=argparse.SUPPRESS)
    parser.add_argument('--artifact-dir', type=Path, default=Path(get_settings().database_path).resolve().parent / 'router-encoders')
    args = parser.parse_args()
    try:
        prepared = prepare(args)
        if args.automatic or prepared is True:
            run_predictor_preparation(args.controller_owner)
    except (KeyboardInterrupt, EOFError):
        print('Preparation cancelled; no partial calibration was activated.', file=sys.stderr)
        return 1
    except Exception as exc:
        print(str(exc) if isinstance(exc, ValueError) else f'Preparation failed ({type(exc).__name__}). Check dependencies, download access and Ollama availability.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
