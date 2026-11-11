"""Aplicativo desktop local. Não envia e-mails nem mensagens automaticamente."""

from __future__ import annotations

import sqlite3
import tempfile
import tkinter as tk
import webbrowser
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .core import STAGES, Store, cents, decimal_quantity, line_total, money, quantity, seed_demo

BG, WHITE, INK, MUTED = "#f4f5fa", "#ffffff", "#20273e", "#747b91"
PURPLE, NAVY, BORDER = "#6653c7", "#20233c", "#e2e4ee"


def label(parent, text, size=10, color=INK, bold=False, bg=BG, **kwargs):
    return tk.Label(parent, text=text, fg=color, bg=bg,
                    font=("Segoe UI Semibold" if bold else "Segoe UI", size), **kwargs)


def button(parent, text, command, primary=False):
    return ttk.Button(parent, text=text, command=command, style="Primary.TButton" if primary else "TButton")


def center(window, parent, width, height):
    window.update_idletasks()
    screen_w, screen_h = window.winfo_screenwidth(), window.winfo_screenheight()
    width, height = min(width, screen_w - 40), min(height, screen_h - 100)
    x = max(10, min(parent.winfo_rootx() + (parent.winfo_width() - width) // 2, screen_w - width - 20))
    y = max(10, min(parent.winfo_rooty() + (parent.winfo_height() - height) // 2, screen_h - height - 70))
    window.geometry(f"{width}x{height}+{x}+{y}")


def table(parent, columns, height=8):
    box = tk.Frame(parent, bg=WHITE)
    tree = ttk.Treeview(box, columns=tuple(c[0] for c in columns), show="headings", selectmode="browse", height=height)
    for key, title, width in columns:
        tree.heading(key, text=title)
        tree.column(key, width=width, minwidth=65)
    vertical = ttk.Scrollbar(box, command=tree.yview)
    horizontal = ttk.Scrollbar(box, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    horizontal.pack(side="bottom", fill="x")
    vertical.pack(side="right", fill="y")
    tree.pack(fill="both", expand=True)
    return box, tree


def safe_action(app, action):
    try:
        return action()
    except (OSError, ValueError, sqlite3.Error) as error:
        messagebox.showerror("Não foi possível concluir", str(error), parent=app)
        return None


class Form(tk.Toplevel):
    """Formulário simples reutilizável para clientes, tarefas e perfil."""
    def __init__(self, app, title, fields, save):
        super().__init__(app)
        self.title(title)
        self.configure(bg=WHITE)
        self.geometry("540x620")
        self.minsize(480, 520)
        self.transient(app)
        self.grab_set()
        self.app = app
        self.values = {}
        body = tk.Frame(self, bg=WHITE, padx=24, pady=20)
        body.pack(fill="both", expand=True)
        label(body, title, 18, bold=True, bg=WHITE).pack(anchor="w", pady=(0, 14))
        for key, title_text, initial, multiline in fields:
            label(body, title_text, color=MUTED, bg=WHITE).pack(anchor="w", pady=(6, 3))
            if multiline:
                widget = tk.Text(body, height=4, wrap="word", font=("Segoe UI", 10), relief="solid", bd=1)
                widget.insert("1.0", initial)
                widget.pack(fill="both", expand=True)
            else:
                widget = ttk.Entry(body)
                widget.insert(0, initial)
                widget.pack(fill="x")
            self.values[key] = (widget, multiline)
        def submit():
            def execute():
                values = {key: w.get("1.0", "end-1c") if multiline else w.get() for key, (w, multiline) in self.values.items()}
                save(values)
                app.refresh()
                self.destroy()
            safe_action(self, execute)
        bottom = tk.Frame(body, bg=WHITE)
        bottom.pack(fill="x", pady=(20, 0))
        button(bottom, "Salvar", submit, True).pack(side="right")
        button(bottom, "Cancelar", self.destroy).pack(side="right", padx=8)
        next(iter(self.values.values()))[0].focus_set()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after_idle(lambda: center(self, app, 540, 620))


class QuoteEditor(tk.Toplevel):
    def __init__(self, app, quote_id=None):
        super().__init__(app)
        self.title("Editar rascunho" if quote_id else "Novo orçamento")
        self.geometry("950x730")
        self.minsize(860, 680)
        self.configure(bg=BG)
        self.transient(app)
        self.grab_set()
        self.app, self.quote_id = app, quote_id
        self.items = []
        self.customer_map = {f"{c['id']} · {c['name']}": c["id"] for c in app.store.customers()}
        old = app.store.quote(quote_id) if quote_id else None
        self.customer = tk.StringVar(value=next(iter(self.customer_map), ""))
        self.title_var = tk.StringVar(value=old["title"] if old else "")
        self.expires = tk.StringVar(value=old["expires"] if old else (date.today() + timedelta(days=15)).isoformat())
        self.discount = tk.StringVar(value=str(Decimal(old["discount_cents"]) / 100) if old else "0,00")
        self.description, self.qty, self.price = tk.StringVar(), tk.StringVar(value="1"), tk.StringVar()
        self.total = tk.StringVar(value="Total: R$ 0,00")
        if old:
            self.customer.set(next(k for k, value in self.customer_map.items() if value == old["customer_id"]))
            self.items = [{"description": i["description"], "quantity": decimal_quantity(i["qty_milli"]),
                           "unit_price": str(Decimal(i["unit_cents"]) / 100)} for i in old["items"]]
        body = tk.Frame(self, bg=BG, padx=22, pady=18)
        body.pack(fill="both", expand=True)
        label(body, "Uma proposta clara, do início ao fim.", 19, bold=True).pack(anchor="w", pady=(0, 12))
        top = tk.Frame(body, bg=BG)
        top.pack(fill="x")
        for col, (text, variable, width) in enumerate((("Cliente", self.customer, 35), ("Validade (AAAA-MM-DD)", self.expires, 20), ("Desconto em R$", self.discount, 16))):
            field = tk.Frame(top, bg=BG)
            field.grid(row=0, column=col, sticky="ew", padx=(0, 12 if col < 2 else 0))
            top.columnconfigure(col, weight=2 if col == 0 else 1)
            label(field, text, 9, MUTED).pack(anchor="w")
            widget = ttk.Combobox(field, textvariable=variable, values=list(self.customer_map), state="readonly") if col == 0 else ttk.Entry(field, textvariable=variable, width=width)
            widget.pack(fill="x", pady=(4, 0))
        label(body, "Título do orçamento", 9, MUTED).pack(anchor="w", pady=(10, 3))
        ttk.Entry(body, textvariable=self.title_var).pack(fill="x")
        label(body, "ITENS DA PROPOSTA", 9, PURPLE, True).pack(anchor="w", pady=(15, 7))
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x")
        for text, variable, width, expand in (("Descrição", self.description, 35, True), ("Quantidade", self.qty, 10, False), ("Valor unitário (R$)", self.price, 18, False)):
            field = tk.Frame(row, bg=BG)
            field.pack(side="left", fill="x", expand=expand, padx=(0, 8))
            label(field, text, 9, MUTED).pack(anchor="w")
            ttk.Entry(field, textvariable=variable, width=width).pack(fill="x", pady=(3, 0))
        actions = tk.Frame(body, bg=BG)
        actions.pack(fill="x", pady=8)
        button(actions, "Adicionar item", self.add_item, True).pack(side="left")
        button(actions, "Atualizar selecionado", self.update_item).pack(side="left", padx=8)
        button(actions, "Remover selecionado", self.remove_item).pack(side="left")
        # Reserva condições e botões antes da tabela flexível.
        bottom = tk.Frame(body, bg=BG)
        bottom.pack(side="bottom", fill="x", pady=(12, 0))
        button(bottom, "Salvar rascunho", self.save, True).pack(side="right")
        button(bottom, "Cancelar", self.destroy).pack(side="right", padx=8)
        tk.Label(bottom, textvariable=self.total, bg=BG, fg=PURPLE, font=("Segoe UI Semibold", 16)).pack(side="left")
        notes_box = tk.Frame(body, bg=BG)
        notes_box.pack(side="bottom", fill="x", pady=(10, 0))
        label(notes_box, "Condições, prazo e escopo", 9, MUTED).pack(anchor="w", pady=(0, 4))
        self.notes = tk.Text(notes_box, height=4, font=("Segoe UI", 10), wrap="word", relief="solid", bd=1)
        self.notes.pack(fill="x")
        if old:
            self.notes.insert("1.0", old["notes"])
        box, self.tree = table(body, (("description", "DESCRIÇÃO", 410), ("qty", "QTD.", 100),
                                     ("unit", "VALOR UNITÁRIO", 150), ("total", "TOTAL", 150)), 4)
        box.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.selected)
        self.discount.trace_add("write", lambda *_: self.render())
        self.render()
        self.after_idle(lambda: center(self, app, 950, 730))
        self.bind("<Escape>", lambda _e: self.destroy())

    def item_input(self):
        if not self.description.get().strip():
            raise ValueError("Preencha a descrição do item.")
        quantity(self.qty.get())
        cents(self.price.get())
        return {"description": self.description.get().strip(), "quantity": self.qty.get(), "unit_price": self.price.get()}

    def add_item(self):
        def add():
            self.items.append(self.item_input())
            self.description.set("")
            self.qty.set("1")
            self.price.set("")
            self.render()
        safe_action(self, add)

    def clear_input(self):
        self.description.set("")
        self.qty.set("1")
        self.price.set("")

    def selected(self, _event=None):
        selected = self.tree.selection()
        if selected:
            item = self.items[int(selected[0])]
            self.description.set(item["description"])
            self.qty.set(item["quantity"])
            self.price.set(item["unit_price"])

    def update_item(self):
        def update():
            selected = self.tree.selection()
            if not selected:
                raise ValueError("Selecione um item na tabela.")
            self.items[int(selected[0])] = self.item_input()
            self.render()
            self.clear_input()
        safe_action(self, update)

    def remove_item(self):
        selected = self.tree.selection()
        if selected:
            self.items.pop(int(selected[0]))
            self.render()
            self.clear_input()

    def render(self):
        self.tree.delete(*self.tree.get_children())
        subtotal = 0
        for index, item in enumerate(self.items):
            total = line_total(quantity(item["quantity"]), cents(item["unit_price"]))
            subtotal += total
            self.tree.insert("", "end", iid=str(index), values=(item["description"], item["quantity"], money(cents(item["unit_price"])), money(total)))
        try:
            self.total.set("Total: " + money(subtotal - cents(self.discount.get())))
        except ValueError:
            self.total.set("Confira o desconto")

    def save(self):
        def save():
            if self.description.get().strip() and not self.tree.selection():
                raise ValueError("Clique em Adicionar item para incluir o item preenchido antes de salvar.")
            if self.description.get().strip() and self.tree.selection():
                if self.item_input() != self.items[int(self.tree.selection()[0])]:
                    raise ValueError("Clique em Atualizar selecionado para confirmar a alteração do item.")
            quote_id = self.app.store.save_quote(self.customer_map[self.customer.get()], self.title_var.get(),
                                                self.expires.get(), self.items, self.discount.get(),
                                                self.notes.get("1.0", "end-1c"), self.quote_id)
            self.app.query_quote.set("")
            self.app.stage_filter.set("Todos")
            self.app.refresh()
            self.app.tabs.select(self.app.quotes_tab)
            self.app.quote_tree.selection_set(str(quote_id))
            self.app.quote_tree.see(str(quote_id))
            self.app.status.set("Rascunho salvo. Confira e altere a etapa quando enviar ao cliente.")
            self.destroy()
        safe_action(self, save)


class Application(tk.Tk):
    def __init__(self, directory=None, demo=False):
        super().__init__()
        self.title("OrçaFlow — propostas que avançam")
        self.geometry(f"{min(1280, self.winfo_screenwidth()-60)}x{min(880,self.winfo_screenheight()-90)}")
        self.minsize(1080, 680)
        self.configure(bg=BG)
        self.default_store = Store(directory)
        self.store = self.default_store
        self.demo_mode = False
        self.query_customer, self.query_quote = tk.StringVar(), tk.StringVar()
        self.stage_filter = tk.StringVar(value="Todos")
        self.status = tk.StringVar(value="Tudo salvo neste computador. Comece cadastrando um cliente ou experimente a demonstração.")
        self._style()
        self._layout()
        self.query_customer.trace_add("write", lambda *_: self.refresh_customers())
        self.query_quote.trace_add("write", lambda *_: self.refresh_quotes())
        self.stage_filter.trace_add("write", lambda *_: self.refresh_quotes())
        self.refresh()
        if demo:
            self.switch_demo()
        self.after(60000, self.periodic_refresh)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        self.option_add("*Font", ("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("TButton", padding=(13, 8), background=WHITE, foreground=INK, bordercolor=BORDER)
        style.map("TButton", background=[("active", "#eeeafa")])
        style.configure("Primary.TButton", background=PURPLE, foreground=WHITE, borderwidth=0)
        style.map("Primary.TButton", background=[("active", "#5141a6")])
        style.configure("TEntry", fieldbackground=WHITE, padding=8, bordercolor=BORDER)
        style.configure("TCombobox", fieldbackground=WHITE, padding=7)
        style.configure("Treeview", background=WHITE, fieldbackground=WHITE, foreground=INK, rowheight=38, borderwidth=0)
        style.map("Treeview", background=[("selected", "#e7e1fb")], foreground=[("selected", INK)])
        style.configure("Treeview.Heading", background="#eeeef6", foreground=MUTED, relief="flat", padding=(8, 10), font=("Segoe UI Semibold", 9))
        style.configure("TNotebook", borderwidth=0, background=BG)
        style.configure("TNotebook.Tab", padding=(16, 11), background=BG, foreground=MUTED)
        style.map("TNotebook.Tab", background=[("selected", WHITE)], foreground=[("selected", PURPLE)])

    def _layout(self):
        sidebar = tk.Frame(self, width=190, bg=NAVY)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        label(sidebar, "◈", 33, "#b9a9ff", bg=NAVY).pack(anchor="w", padx=24, pady=(28, 4))
        label(sidebar, "OrçaFlow", 23, WHITE, True, NAVY).pack(anchor="w", padx=24)
        label(sidebar, "DO CONTATO À CONQUISTA", 7, "#a9abc4", bg=NAVY).pack(anchor="w", padx=24, pady=(6, 28))
        self.nav = []
        for index, text in enumerate(("Visão geral", "Clientes", "Orçamentos", "Agenda", "Meu negócio")):
            btn = tk.Button(sidebar, text=text, anchor="w", bg=NAVY, fg="#c9cadd", activebackground="#363550",
                            activeforeground=WHITE, relief="flat", padx=20, pady=13, font=("Segoe UI", 10),
                            cursor="hand2", command=lambda i=index: self.tabs.select(i))
            btn.pack(fill="x", padx=10, pady=2)
            self.nav.append(btn)
        bottom = tk.Frame(sidebar, bg=NAVY)
        bottom.pack(side="bottom", fill="x", padx=18, pady=24)
        self.demo_button = tk.Button(bottom, text="Experimentar demo", bg="#363550", fg=WHITE,
                                     activebackground="#5141a6", activeforeground=WHITE, relief="flat", pady=11,
                                     command=lambda: safe_action(self, self.switch_demo), cursor="hand2")
        self.demo_button.pack(fill="x", pady=(0, 15))
        label(bottom, "●  DADOS LOCAIS", 8, "#b9a9ff", True, NAVY).pack(anchor="w")
        label(bottom, "Sem conta. Sem assinatura.\nVocê controla seus dados.", 9, "#a9abc4", bg=NAVY, justify="left").pack(anchor="w", pady=(8, 14))
        label(bottom, f"v{__version__} · Leonardo Santos", 8, "#a9abc4", bg=NAVY).pack(anchor="w")
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=28, pady=22)
        top = tk.Frame(main, bg=BG)
        top.pack(fill="x", pady=(0, 16))
        self.heading = label(top, "Seu trabalho merece seguir em frente.", 22, bold=True)
        self.heading.pack(anchor="w")
        label(top, "Clientes, propostas e próximos passos. Tudo em um só lugar.", 10, MUTED).pack(anchor="w", pady=(5, 0))
        tk.Label(main, textvariable=self.status, bg=BG, fg=MUTED, font=("Segoe UI", 9),
                 wraplength=920, height=2, anchor="w", justify="left").pack(side="bottom", fill="x", pady=(12, 0))
        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill="both", expand=True)
        self.pages = [ttk.Frame(self.tabs, padding=15) for _ in range(5)]
        for page, text in zip(self.pages, ("Visão geral", "Clientes", "Orçamentos", "Agenda", "Meu negócio")):
            self.tabs.add(page, text=text)
        self.tabs.bind("<<NotebookTabChanged>>", self.navigation)
        self.dashboard_tab, self.customers_tab, self.quotes_tab, self.tasks_tab, self.settings_tab = self.pages
        self._dashboard()
        self._customers()
        self._quotes()
        self._tasks()
        self._settings()

    def navigation(self, _event=None):
        selected = self.tabs.index(self.tabs.select())
        for index, btn in enumerate(self.nav):
            btn.configure(bg="#363550" if index == selected else NAVY, fg=WHITE if index == selected else "#c9cadd")

    def _dashboard(self):
        page = self.dashboard_tab
        row = tk.Frame(page, bg=BG)
        row.pack(fill="x", pady=(0, 20))
        self.metrics = {}
        for index, (key, title, hint) in enumerate((("customers", "CLIENTES", "relacionamentos registrados"),
                                                   ("pipeline", "EM NEGOCIAÇÃO", "propostas enviadas e negociadas"),
                                                   ("approved", "APROVADOS", "total de orçamentos aprovados"))):
            card = tk.Frame(row, bg=WHITE, padx=18, pady=18, highlightbackground=BORDER, highlightthickness=1)
            card.grid(row=0, column=index, sticky="ew", padx=(0, 12 if index < 2 else 0))
            row.columnconfigure(index, weight=1, uniform="stats")
            label(card, title, 8, MUTED, True, WHITE).pack(anchor="w")
            value = tk.StringVar(value="0")
            self.metrics[key] = value
            tk.Label(card, textvariable=value, bg=WHITE, fg=PURPLE if index else INK, font=("Segoe UI Semibold", 24)).pack(anchor="w", pady=(7, 2))
            label(card, hint, 8, MUTED, bg=WHITE).pack(anchor="w")
        bar = tk.Frame(page, bg=BG)
        bar.pack(fill="x")
        label(bar, "Cada proposta tem um próximo passo.", 15, bold=True).pack(side="left")
        button(bar, "+ Novo orçamento", self.new_quote, True).pack(side="right")
        self.pipeline_text = tk.StringVar()
        tk.Label(page, textvariable=self.pipeline_text, bg=BG, fg=MUTED, anchor="w", justify="left",
                 wraplength=900, font=("Segoe UI", 10)).pack(fill="x", pady=(10, 18))
        label(page, "PRÓXIMOS CONTATOS", 9, PURPLE, True).pack(anchor="w", pady=(0, 8))
        box, self.due_tree = table(page, (("due", "DATA", 115), ("title", "AÇÃO", 440), ("quote", "ORÇAMENTO", 250)), 5)
        box.pack(fill="both", expand=True)
        self.due_tree.tag_configure("late", foreground="#a8483c", background="#fff4f1")
        self.due_tree.bind("<Double-1>", lambda _e: self.tabs.select(self.tasks_tab))
        label(page, "Os lembretes aparecem aqui; nenhuma mensagem é enviada automaticamente.", 9, MUTED).pack(anchor="w", pady=(10, 0))

    def _customers(self):
        page = self.customers_tab
        toolbar = tk.Frame(page, bg=BG)
        toolbar.pack(fill="x", pady=(0, 15))
        ttk.Entry(toolbar, textvariable=self.query_customer, width=26).pack(side="left", padx=(0, 10))
        button(toolbar, "Importar CSV", self.import_customers).pack(side="right", padx=(8, 0))
        button(toolbar, "Editar", self.edit_customer).pack(side="right", padx=(8, 0))
        button(toolbar, "+ Novo cliente", self.new_customer, True).pack(side="right")
        label(page, "Busque por nome, empresa, e-mail ou telefone.", 9, MUTED).pack(anchor="w", pady=(0, 10))
        box, self.customer_tree = table(page, (("name", "NOME", 220), ("company", "EMPRESA", 210),
                                              ("email", "E-MAIL", 240), ("phone", "TELEFONE", 150)))
        box.pack(fill="both", expand=True)
        self.customer_tree.bind("<Double-1>", lambda _e: self.edit_customer())

    def _quotes(self):
        page = self.quotes_tab
        toolbar = tk.Frame(page, bg=BG)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Entry(toolbar, textvariable=self.query_quote, width=24).pack(side="left", padx=(0, 8))
        ttk.Combobox(toolbar, textvariable=self.stage_filter, values=("Todos", *STAGES), state="readonly", width=15).pack(side="left")
        button(toolbar, "+ Novo orçamento", self.new_quote, True).pack(side="right")
        bar = tk.Frame(page, bg=BG)
        bar.pack(fill="x", pady=(0, 12))
        for text, action in (("Editar", self.edit_quote), ("Duplicar", self.duplicate_quote),
                             ("Alterar etapa", self.change_stage), ("Exportar proposta", self.export_proposal),
                             ("Copiar mensagem", self.copy_message)):
            button(bar, text, action).pack(side="left", padx=(0, 6))
        detail = tk.Frame(page, bg=BG)
        detail.pack(side="bottom", fill="x", pady=(12, 0))
        self.quote_note = tk.StringVar(value="Selecione uma proposta para ver o histórico. Duplo clique abre o rascunho.")
        tk.Label(detail, textvariable=self.quote_note, bg=BG, fg=MUTED, wraplength=850,
                 height=3, anchor="w", justify="left", font=("Segoe UI", 9)).pack(fill="x")
        box, self.quote_tree = table(page, (("number", "NÚMERO", 155), ("title", "PROPOSTA / CLIENTE", 330),
                                           ("stage", "ETAPA", 130), ("expires", "VALIDADE", 110), ("total", "TOTAL", 145)))
        box.pack(fill="both", expand=True)
        self.quote_tree.tag_configure("expired", foreground="#a8483c", background="#fff4f1")
        self.quote_tree.bind("<<TreeviewSelect>>", self.quote_details)
        self.quote_tree.bind("<Double-1>", lambda _e: self.edit_quote())

    def _tasks(self):
        page = self.tasks_tab
        toolbar = tk.Frame(page, bg=BG)
        toolbar.pack(fill="x", pady=(0, 14))
        label(toolbar, "A próxima conversa não precisa ficar na memória.", 13, bold=True).pack(side="left")
        button(toolbar, "+ Nova tarefa", self.new_task, True).pack(side="right")
        button(toolbar, "Concluir selecionada", self.complete_task).pack(side="right", padx=8)
        label(page, "Ao marcar Enviado ou Negociação, um retorno é agendado automaticamente para daqui a 3 ou 2 dias.", 9, MUTED).pack(anchor="w", pady=(0, 12))
        box, self.task_tree = table(page, (("due", "DATA", 115), ("title", "AÇÃO", 380), ("quote", "PROPOSTA", 270), ("type", "ORIGEM", 110)))
        box.pack(fill="both", expand=True)
        self.task_tree.tag_configure("late", foreground="#a8483c", background="#fff4f1")

    def _settings(self):
        page = self.settings_tab
        label(page, "Seu nome em cada proposta.", 17, bold=True).pack(anchor="w", pady=(0, 8))
        label(page, "Configure o cabeçalho das propostas e mantenha uma cópia dos dados.", 10, MUTED).pack(anchor="w", pady=(0, 18))
        self.profile_note = tk.StringVar()
        tk.Label(page, textvariable=self.profile_note, bg=WHITE, fg=INK, font=("Segoe UI", 11),
                 justify="left", anchor="w", padx=18, pady=18, height=3).pack(fill="x")
        row = tk.Frame(page, bg=BG)
        row.pack(fill="x", pady=(14, 24))
        button(row, "Editar meu negócio", self.edit_profile, True).pack(side="left")
        label(page, "SEUS DADOS, SOB SEU CONTROLE", 9, PURPLE, True).pack(anchor="w", pady=(0, 12))
        row2 = tk.Frame(page, bg=BG)
        row2.pack(fill="x")
        button(row2, "Criar backup", self.backup).pack(side="left", padx=(0, 8))
        button(row2, "Restaurar backup", self.restore).pack(side="left", padx=(0, 8))
        button(row2, "Exportar orçamentos CSV", self.export_quotes).pack(side="left")
        self.data_note = tk.StringVar()
        tk.Label(page, textvariable=self.data_note, bg=BG, fg=MUTED, wraplength=820, anchor="w",
                 justify="left", font=("Segoe UI", 9)).pack(fill="x", pady=20)
        label(page, "OrçaFlow organiza propostas e lembretes. Valores aprovados não representam pagamentos recebidos.\nPropostas exportadas não são documentos fiscais. Não há sincronização entre computadores.",
              9, MUTED, justify="left", wraplength=850).pack(anchor="w", pady=(0, 18))
        button(page, "Ajuda e atalhos de uso", self.help).pack(anchor="w")

    def periodic_refresh(self):
        safe_action(self, self.refresh_dashboard)
        self.after(60000, self.periodic_refresh)

    def refresh(self):
        self.refresh_customers()
        self.refresh_quotes()
        self.refresh_dashboard()
        self.refresh_tasks()
        settings = self.store.settings()
        self.profile_note.set("\n".join((settings.get("company") or "Seu negócio ainda não foi configurado", settings.get("email", ""), settings.get("phone", ""))))
        self.data_note.set(f"Dados atuais: {self.store.path}\nFaça backups regularmente e guarde uma cópia em outro local. A restauração preserva uma cópia da base anterior.")

    def refresh_customers(self):
        selection = self.customer_tree.selection()
        self.customer_tree.delete(*self.customer_tree.get_children())
        for customer in self.store.customers(self.query_customer.get()):
            self.customer_tree.insert("", "end", iid=str(customer["id"]), values=tuple(customer[k] for k in ("name", "company", "email", "phone")))
        if selection and self.customer_tree.exists(selection[0]):
            self.customer_tree.selection_set(selection[0])

    def refresh_quotes(self):
        selection = self.quote_tree.selection()
        self.quote_tree.delete(*self.quote_tree.get_children())
        for q in self.store.quotes(self.query_quote.get(), self.stage_filter.get()):
            self.quote_tree.insert("", "end", iid=str(q["id"]), values=(q["number"], q["title"] + " · " + q["customer"]["name"],
                                   q["stage"], q["expires"] + (" !" if q["expired"] else ""), money(q["total"])), tags=("expired",) if q["expired"] else ())
        if selection and self.quote_tree.exists(selection[0]):
            self.quote_tree.selection_set(selection[0])

    def refresh_dashboard(self):
        stats = self.store.dashboard()
        for key, variable in self.metrics.items():
            variable.set(money(stats[key]) if key != "customers" else str(stats[key]))
        self.pipeline_text.set("   ·   ".join(f"{stage}: {count}" for stage, count in stats["stages"].items()) +
                               f"\n{stats['overdue']} tarefa(s) atrasada(s) · {stats['expired']} proposta(s) com validade vencida.")
        self.due_tree.delete(*self.due_tree.get_children())
        for task in self.store.tasks()[:20]:
            self.due_tree.insert("", "end", iid=str(task["id"]), values=(task["due"], task["title"], task["quote_title"] or "—"),
                                 tags=("late",) if task["due"] < date.today().isoformat() else ())

    def refresh_tasks(self):
        self.task_tree.delete(*self.task_tree.get_children())
        for task in self.store.tasks():
            self.task_tree.insert("", "end", iid=str(task["id"]), values=(task["due"], task["title"], task["quote_title"] or "—",
                                  "Automático" if task["automatic"] else "Manual"), tags=("late",) if task["due"] < date.today().isoformat() else ())

    def selected(self, tree, name):
        selection = tree.selection()
        if not selection:
            messagebox.showinfo("Selecione um registro", f"Selecione {name} na tabela.", parent=self)
            return None
        return int(selection[0])

    def new_customer(self):
        self.customer_form()

    def edit_customer(self):
        customer_id = self.selected(self.customer_tree, "um cliente")
        if customer_id:
            self.customer_form(customer_id)

    def customer_form(self, customer_id=None):
        old = self.store.customer(customer_id) if customer_id else {}
        fields = [(key, title, old.get(key, ""), key == "notes") for key, title in (("name", "Nome *"), ("company", "Empresa"),
                  ("email", "E-mail"), ("phone", "Telefone"), ("notes", "Observações internas"))]
        Form(self, "Editar cliente" if customer_id else "Novo cliente", fields,
             lambda values: self.store.save_customer(**values, customer_id=customer_id))

    def import_customers(self):
        path = filedialog.askopenfilename(parent=self, title="CSV: nome;empresa;email;telefone;observacoes", filetypes=[("CSV", "*.csv")])
        if path:
            def action():
                result = self.store.import_customers(path)
                self.refresh()
                self.status.set(f"Importação: {result['added']} cliente(s) cadastrado(s), {result['skipped']} e-mail(s) já existente(s) ignorado(s).")
            safe_action(self, action)

    def new_quote(self):
        if not self.store.customers():
            messagebox.showinfo("Primeiro, um cliente", "Cadastre um cliente para começar seu orçamento.", parent=self)
            self.tabs.select(self.customers_tab)
            self.new_customer()
            return
        QuoteEditor(self)

    def edit_quote(self):
        quote_id = self.selected(self.quote_tree, "um orçamento")
        if quote_id:
            if self.store.quote(quote_id)["stage"] != "Rascunho":
                messagebox.showinfo("Proposta preservada", "Somente rascunhos podem ser editados. Clique em Duplicar para criar uma nova versão.", parent=self)
                return
            QuoteEditor(self, quote_id)

    def duplicate_quote(self):
        quote_id = self.selected(self.quote_tree, "um orçamento")
        if quote_id:
            def action():
                new_id = self.store.duplicate_quote(quote_id)
                self.query_quote.set("")
                self.stage_filter.set("Todos")
                self.refresh()
                QuoteEditor(self, new_id)
            safe_action(self, action)

    def change_stage(self):
        quote_id = self.selected(self.quote_tree, "um orçamento")
        if not quote_id:
            return
        dialog = tk.Toplevel(self)
        dialog.title("Alterar etapa")
        dialog.geometry("440x260")
        dialog.configure(bg=WHITE)
        dialog.transient(self)
        dialog.grab_set()
        label(dialog, "Qual é o próximo passo?", 17, bold=True, bg=WHITE).pack(anchor="w", padx=24, pady=(24, 16))
        value = tk.StringVar(value=self.store.quote(quote_id)["stage"])
        ttk.Combobox(dialog, textvariable=value, values=STAGES[1:], state="readonly").pack(fill="x", padx=24)
        label(dialog, "Enviado e Negociação criam um lembrete.\nEtapas finais encerram retornos automáticos.", 9, MUTED, bg=WHITE, justify="left").pack(anchor="w", padx=24, pady=15)
        def save():
            def action():
                self.store.set_stage(quote_id, value.get())
                self.refresh()
                self.status.set("Etapa atualizada. Confira a agenda para o próximo contato.")
                dialog.destroy()
            safe_action(dialog, action)
        button(dialog, "Salvar etapa", save, True).pack(anchor="e", padx=24)
        dialog.after_idle(lambda: center(dialog, self, 440, 260))

    def quote_details(self, _event=None):
        selected = self.quote_tree.selection()
        if selected:
            q = self.store.quote(int(selected[0]))
            events = " | ".join(datetime.fromisoformat(e["created"]).astimezone().strftime("%d/%m %H:%M") + " " + e["description"] for e in q["events"][:3])
            self.quote_note.set(f"{q['number']} · {q['customer']['name']} · {len(q['items'])} item(ns)\n{events}")

    def export_proposal(self):
        quote_id = self.selected(self.quote_tree, "um orçamento")
        if quote_id:
            path = filedialog.asksaveasfilename(parent=self, initialfile=self.store.quote(quote_id)["number"] + ".html",
                                              defaultextension=".html", filetypes=[("Proposta HTML para impressão", "*.html")])
            if path:
                def action():
                    self.store.export_proposal(quote_id, path)
                    webbrowser.open(Path(path).resolve().as_uri())
                    self.status.set("Proposta exportada. No navegador, use Imprimir para salvar como PDF. O arquivo contém os dados do cliente.")
                safe_action(self, action)

    def copy_message(self):
        quote_id = self.selected(self.quote_tree, "um orçamento")
        if quote_id:
            self.clipboard_clear()
            self.clipboard_append(self.store.message(quote_id))
            self.status.set("Texto copiado. Revise e cole na conversa com o cliente; nenhuma mensagem foi enviada.")

    def new_task(self):
        Form(self, "Nova tarefa", [("title", "O que precisa ser feito? *", "", False),
                                   ("due", "Data (AAAA-MM-DD) *", date.today().isoformat(), False)],
             lambda values: self.store.add_task(**values))

    def complete_task(self):
        task_id = self.selected(self.task_tree, "uma tarefa")
        if task_id:
            def action():
                self.store.complete_task(task_id)
                self.refresh()
                self.status.set("Tarefa concluída.")
            safe_action(self, action)

    def edit_profile(self):
        old = self.store.settings()
        Form(self, "Meu negócio", [(key, title, old.get(key, ""), key == "footer") for key, title in
                                   (("company", "Nome do negócio"), ("email", "E-mail"), ("phone", "Telefone"), ("footer", "Rodapé das propostas"))],
             lambda values: self.store.save_settings(**values))

    def backup(self):
        path = filedialog.asksaveasfilename(parent=self, initialfile=f"orcaflow-backup-{datetime.now():%Y%m%d-%H%M%S}.sqlite3",
                                          defaultextension=".sqlite3", filetypes=[("Backup OrçaFlow", "*.sqlite3")])
        if path:
            def action():
                self.store.backup(path)
                self.status.set(f"Backup criado: {path}")
            safe_action(self, action)

    def restore(self):
        path = filedialog.askopenfilename(parent=self, title="Restaurar backup do OrçaFlow", filetypes=[("Backup OrçaFlow", "*.sqlite3")])
        if path and messagebox.askyesno("Restaurar backup", "Substituir os dados atuais pelos dados deste backup?\n\nUma cópia dos dados atuais será preservada antes da restauração.", parent=self):
            def action():
                safety = self.store.restore(path)
                self.refresh()
                self.status.set(f"Backup restaurado. Cópia anterior preservada em: {safety}")
            safe_action(self, action)

    def export_quotes(self):
        path = filedialog.asksaveasfilename(parent=self, initialfile=f"orcamentos-{datetime.now():%Y%m%d-%H%M%S}.csv",
                                          defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if path:
            def action():
                self.store.export_quotes(path)
                self.status.set(f"Orçamentos exportados: {path}. Valores em centavos para preservar a precisão.")
            safe_action(self, action)

    def switch_demo(self):
        if self.demo_mode:
            self.store = self.default_store
            self.demo_mode = False
            self.demo_button.configure(text="Experimentar demo")
            self.heading.configure(text="Seu trabalho merece seguir em frente.")
            self.status.set("Você voltou aos seus dados locais.")
        else:
            self.store = Store(Path(tempfile.mkdtemp(prefix="OrcaFlow-demo-")))
            seed_demo(self.store)
            self.demo_mode = True
            self.demo_button.configure(text="Voltar aos meus dados")
            self.heading.configure(text="Demonstração · explore com dados fictícios.")
            self.status.set("Modo demonstração: dados fictícios em uma pasta temporária. Seus dados reais continuam separados.")
        self.query_customer.set("")
        self.query_quote.set("")
        self.stage_filter.set("Todos")
        self.refresh()
        self.tabs.select(self.dashboard_tab)

    def help(self):
        messagebox.showinfo("Como usar o OrçaFlow", "1. Configure Meu negócio.\n2. Cadastre ou importe clientes por CSV.\n3. Crie um orçamento e adicione seus itens.\n4. Confira a proposta e exporte para impressão.\n5. Ao enviar por conta própria, marque como Enviado.\n6. Confira os retornos na Agenda.\n\nA mensagem de retorno é copiada para você revisar e enviar. Propostas enviadas são preservadas; duplique para editar.\n\nBackup e restauração ficam em Meu negócio.\nNenhuma mensagem ou dado é enviado automaticamente.\n\ngithub.com/LeoDevsn/orcaflow", parent=self)


def launch(directory=None, demo=False):
    app = Application(directory, demo)
    app.mainloop()
