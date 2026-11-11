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
    parser.add_argument("--server", action="store_true", help="Inicia só o servidor, sem janela de controle")
    parser.add_argument("--host", default="127.0.0.1", help="Endereço de escuta (padrão: somente este computador)")
    parser.add_argument("--port", type=int, default=7460)
    parser.add_argument("--legacy", action="store_true", help="Abre a interface antiga, para compatibilidade")
    parser.add_argument("--init-owner", action="store_true", help="Configura o acesso pelo terminal local do servidor")
    parser.add_argument("--reset-password", action="store_true", help="Redefine a senha pelo terminal local do administrador")
    args = parser.parse_args()
    if args.init_owner or args.reset_password:
        import getpass
        from .web import Identity
        identity = Identity(Store(args.data_dir).directory)
        name = input("Seu nome: ").strip() if args.init_owner else None
        password = getpass.getpass("Nova senha (mínimo 10 caracteres): ")
        if password != getpass.getpass("Repita a senha: "):
            raise ValueError("As senhas não conferem. Nenhuma alteração foi feita.")
        if args.init_owner:
            identity.setup(name, password)
        else:
            identity.reset_password(password)
        print("Acesso configurado. Inicie o servidor para entrar.")
    elif args.stats:
        print(json.dumps(Store(args.data_dir).dashboard(), indent=2, ensure_ascii=False))
    elif args.legacy:
        from .gui import launch
        launch(args.data_dir, args.demo)
    else:
        from .server import run
        run(args.data_dir, args.host, args.port, desktop=not args.server, demo=args.demo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
