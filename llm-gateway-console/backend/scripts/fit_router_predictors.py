"""Fit compatible stored evaluations only; no model generations or downloads."""
from pathlib import Path
import sys
import argparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import init_db
from app.learned_router import run_predictor_preparation


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controller-owner', help=argparse.SUPPRESS)
    args = parser.parse_args()
    init_db()
    run_predictor_preparation(args.controller_owner)
    print('Predictor fitting completed. Inspect Models for validation/fallback status.')
