"""Inicialização do servidor WSGI e controle local para usuários sem terminal."""

import json
import logging
import os
import threading
import urllib.error
import urllib.request
import webbrowser

from waitress import create_server

from .core import data_directory
from .web import create_app


def run(directory=None, host="127.0.0.1", port=7460, desktop=True, demo=False):
    directory = directory or data_directory()
    https = os.environ.get("ORCAFLOW_HTTPS") == "1"
    trusted = [h.strip() for h in os.environ.get("ORCAFLOW_TRUSTED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if h.strip()]
    app = create_app(directory, https=https, trusted_hosts=trusted)
    if host not in {"localhost", "127.0.0.1", "::1"} and not app.extensions["orca_identity"].get():
        raise ValueError("Configure seu nome e sua senha neste computador antes de liberar o servidor na rede. Inicie primeiro sem --host.")
    logging.basicConfig(filename=app.extensions["orca_store"].directory / "servidor.log", level=logging.WARNING)
    url = f"http://127.0.0.1:{port}/" + ("?demo=1" if demo else "")
    try:
        server = create_server(app, host=host, port=port, threads=4, max_request_body_size=12 * 1024 * 1024,
                               trusted_proxy=os.environ.get("ORCAFLOW_PROXY_IP", "127.0.0.1") if os.environ.get("ORCAFLOW_PROXY") == "1" else None,
                               trusted_proxy_headers={"x-forwarded-proto"} if os.environ.get("ORCAFLOW_PROXY") == "1" else set())
    except OSError:
        if desktop:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                    if json.load(response).get("app") == "orcaflow":
                        webbrowser.open(url)
                        return
            except (OSError, ValueError):
                pass
        raise ValueError(f"Não foi possível iniciar na porta {port}. Ela pode estar sendo usada por outro aplicativo.") from None
    if not desktop:
        print(f"OrçaFlow em http://{host}:{port} · Ctrl+C para encerrar", flush=True)
        try:
            server.run()
        except KeyboardInterrupt:
            pass
        finally:
            server.close()
            server.task_dispatcher.shutdown(timeout=30)
        return

    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title("OrçaFlow · controle do aplicativo")
    root.geometry("500x330")
    root.resizable(False, False)
    root.configure(bg="#f5f4ef")
    body = tk.Frame(root, bg="#f5f4ef", padx=28, pady=25)
    body.pack(fill="both", expand=True)
    tk.Label(body, text="OrçaFlow está aberto.", font=("Segoe UI Semibold", 20), fg="#223b30", bg="#f5f4ef").pack(anchor="w")
    tk.Label(body, text="Use o aplicativo na aba do seu navegador.\nMantenha esta janela aberta enquanto trabalha.",
             font=("Segoe UI", 11), justify="left", bg="#f5f4ef", fg="#505c54").pack(anchor="w", pady=(12, 18))
    status = tk.Label(body, text=f"Em execução neste computador\n{url.split('?')[0]}", justify="left",
                      font=("Segoe UI", 10), bg="#f5f4ef", fg="#285342")
    status.pack(anchor="w", pady=(0, 18))
    actions = tk.Frame(body, bg="#f5f4ef")
    actions.pack(fill="x")
    ttk.Button(actions, text="Abrir no navegador", command=lambda: webbrowser.open(url)).pack(side="left", padx=(0, 12), ipady=7)
    def close():
        status.configure(text="Encerrando com segurança. Aguarde um momento…")
        for child in actions.winfo_children():
            child.configure(state="disabled")
        def stop():
            server.close()
            server.task_dispatcher.shutdown(timeout=30)
        worker = threading.Thread(target=stop, name="OrcaFlow-encerramento")
        worker.start()
        def wait():
            if worker.is_alive():
                root.after(100, wait)
            else:
                root.destroy()
        wait()
    ttk.Button(actions, text="Encerrar aplicativo", command=close).pack(side="left", ipady=7)
    root.protocol("WM_DELETE_WINDOW", close)
    threading.Thread(target=server.run, name="OrcaFlow-servidor", daemon=True).start()
    root.after(400, lambda: webbrowser.open(url))
    root.mainloop()
