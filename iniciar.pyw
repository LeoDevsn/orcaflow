import traceback

if __name__ == "__main__":
    try:
        from orca_flow.__main__ import main
        main()
    except Exception as error:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Não foi possível abrir o OrçaFlow", f"{error}\n\nFeche outras janelas do aplicativo e tente novamente. Se o problema continuar, procure o responsável pelo computador.")
        root.destroy()
