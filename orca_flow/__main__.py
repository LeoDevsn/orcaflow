import argparse
import json
import sys
from pathlib import Path

from .core import Store


def main():
    parser = argparse.ArgumentParser(description="OrçaFlow: clientes, orçamentos e retornos locais.")
    parser.add_argument("--data-dir", type=Path, help="Pasta alternativa para a base de dados")
    parser.add_argument("--demo", action="store_true", help="Abre uma demonstração isolada")
    parser.add_argument("--stats", action="store_true", help="Exibe indicadores em JSON, sem interface")
    args = parser.parse_args()
    if args.stats:
        print(json.dumps(Store(args.data_dir).dashboard(), indent=2, ensure_ascii=False))
    else:
        from .gui import launch
        launch(args.data_dir, args.demo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
