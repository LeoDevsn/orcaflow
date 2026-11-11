import traceback

if __name__ == "__main__":
    try:
        from orca_flow.__main__ import main
        main()
    except Exception:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("OrçaFlow não iniciou", traceback.format_exc())
        root.destroy()
