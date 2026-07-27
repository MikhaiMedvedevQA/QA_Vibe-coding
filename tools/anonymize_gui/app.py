"""Десктоп-приложение анонимизации документов (Tkinter).

Простой интерфейс над пакетом tools/anonymize/:
  1. «Выбрать файл» — открыть PDF/DOCX/DOC/TXT/XLSX.
  2. «Анонимизировать» — предпросмотр «до / после», псевдонимы подсвечены.
  3. «Сохранить результат» — пишет вывод рядом с исходником + папку ассетов.
  4. «Открыть папку» — открывает каталог с результатом в проводнике.

Запуск:
  python tools/anonymize_gui/app.py
"""

import os
import re
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# Делаем модули tools/anonymize/ доступными для импорта (они используют
# плоские sibling-импорты вроде `from config import ...`).
_PKG = Path(__file__).resolve().parent.parent / "anonymize"
sys.path.insert(0, str(_PKG))

import config  # noqa: E402
import extractors  # noqa: E402
import writers  # noqa: E402
from mapper import Mapper  # noqa: E402
from detectors import load_ignore  # noqa: E402

# Шаблон псевдонима для подсветки в предпросмотре.
_PSEUDO_RE = re.compile(r"[A-Z]+_\d{4}")


class AnonymizeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Анонимизация документов")
        root.geometry("1100x680")

        # Один маппер на сессию — консистентность между файлами и прогонами.
        self.mapper = Mapper()
        self.content = None          # DocumentContent | ExcelContent
        self.source_path: Path | None = None
        self.last_out_path: Path | None = None
        # Состояние навигации по вхождениям выбранного кандидата.
        self._sel_value: str | None = None
        self._sel_positions: dict = {}   # {widget: [offset, ...]}
        self._sel_index: dict = {}       # {widget: int}

        self._build_ui()
        self._set_state("idle")

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # Верх: выбор файла.
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)

        ttk.Button(top, text="Выбрать файл…", command=self.on_select_file).pack(side=tk.LEFT)
        self.file_label = ttk.Label(top, text="файл не выбран", foreground="#555")
        self.file_label.pack(side=tk.LEFT, padx=(8, 0), fill=tk.X, expand=True)

        # Панель действий.
        actions = ttk.Frame(self.root, padding=8)
        actions.pack(fill=tk.X)
        self.btn_run = ttk.Button(actions, text="Анонимизировать (предпросмотр)", command=self.on_anonymize)
        self.btn_run.pack(side=tk.LEFT)
        self.btn_save = ttk.Button(actions, text="Сохранить результат", command=self.on_save)
        self.btn_save.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_open = ttk.Button(actions, text="Открыть папку", command=self.on_open_folder)
        self.btn_open.pack(side=tk.LEFT, padx=(8, 0))
        self.status = ttk.Label(actions, text="", foreground="#0a7")
        self.status.pack(side=tk.LEFT, padx=(12, 0))

        # Предпросмотр: две колонки.
        panes = ttk.Frame(self.root)
        panes.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        left = ttk.LabelFrame(panes, text="До (исходный текст)")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.before_text = self._make_text_widget(left)
        self.before_text.tag_configure("cand", foreground="#b00", background="#ffd0d0")
        self.before_text.tag_configure("sel-cand", foreground="#000", background="#ffff80")
        self.before_text.tag_raise("sel-cand")

        right = ttk.LabelFrame(panes, text="После (псевдонимы подсвечены)")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))
        self.after_text = self._make_text_widget(right)
        self.after_text.tag_configure("pseudo", foreground="#b00", background="#ffe9b3")
        self.after_text.tag_configure("cand", foreground="#b00", background="#ffd0d0")
        self.after_text.tag_configure("sel-cand", foreground="#000", background="#ffff80")
        self.after_text.tag_raise("sel-cand")

        # Панель ревью-кандидатов: подозрительные совпадения, не заменённые
        # детектором (пропущенные продукты/СК/банки/ФИО в контексте).
        rv = ttk.LabelFrame(self.root, text="Кандидаты (требуют ревью)")
        rv.pack(fill=tk.BOTH, padx=8, pady=(0, 8))
        rv_cols = ("value", "type", "reason", "count", "locations")
        self.review_tree = ttk.Treeview(rv, columns=rv_cols, show="headings", height=6)
        rv_titles = {"value": "Значение", "type": "Тип", "reason": "Причина",
                     "count": "N", "locations": "Места"}
        for c, w in (("value", 230), ("type", 70), ("reason", 130),
                     ("count", 40), ("locations", 280)):
            self.review_tree.heading(c, text=rv_titles[c])
            self.review_tree.column(c, width=w)
        self.review_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.review_tree.bind("<<TreeviewSelect>>", self._on_review_select)
        rv_btns = ttk.Frame(rv)
        rv_btns.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))
        self.btn_ignore = ttk.Button(rv_btns, text="В ignore.txt",
                                     command=self.on_ignore, state=tk.DISABLED)
        self.btn_ignore.pack(padx=4, pady=4)
        self.btn_open_review = ttk.Button(rv_btns, text="Открыть _review.json",
                                          command=self.on_open_review, state=tk.DISABLED)
        self.btn_open_review.pack(padx=4, pady=4)
        self.btn_prev = ttk.Button(rv_btns, text="← Пред.",
                                  command=self.on_prev_candidate, state=tk.DISABLED)
        self.btn_prev.pack(padx=4, pady=4)
        self.btn_next = ttk.Button(rv_btns, text="След. →",
                                   command=self.on_next_candidate, state=tk.DISABLED)
        self.btn_next.pack(padx=4, pady=4)

    def _make_text_widget(self, parent) -> tk.Text:
        wrap = tk.Frame(parent)
        wrap.pack(fill=tk.BOTH, expand=True)
        # Гидтер с номерами строк — синхронизирован по вертикали с текстом.
        gutter = tk.Text(
            wrap, width=5, wrap=tk.NONE, font=("Consolas", 10),
            background="#f0f0f0", padx=4, borderwidth=1,
            highlightthickness=0, takefocus=0, state=tk.DISABLED,
        )
        # Текст без переноса строк — одна логическая строка = одна экранная,
        # номера строк слева и справа совпадают построчно.
        txt = tk.Text(wrap, wrap=tk.NONE, undo=False, font=("Consolas", 10),
                      borderwidth=1, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=txt.yview)
        xsb = ttk.Scrollbar(wrap, orient=tk.HORIZONTAL, command=txt.xview)
        # Grid: gutter | txt | vscroll ; (— | hscroll | —)
        wrap.grid_rowconfigure(0, weight=1)
        wrap.grid_columnconfigure(1, weight=1)
        gutter.grid(row=0, column=0, sticky="ns")
        txt.grid(row=0, column=1, sticky="nsew")
        sb.grid(row=0, column=2, sticky="ns")
        xsb.grid(row=1, column=1, sticky="ew")

        def _on_yscroll(*args):
            gutter.yview_moveto(args[0])
            sb.set(*args)

        txt.configure(yscrollcommand=_on_yscroll, xscrollcommand=xsb.set)
        # Связываем гидтер с виджетом для последующего обновления номеров.
        txt._gutter = gutter
        return txt

    def _update_gutter(self, widget: tk.Text) -> None:
        """Перестроить номера строк в гидтере по содержимому текстового виджета."""
        gutter = getattr(widget, "_gutter", None)
        if gutter is None:
            return
        n = int(widget.index("end-1c").split(".")[0])
        gutter.config(state=tk.NORMAL)
        gutter.delete("1.0", tk.END)
        gutter.insert("1.0", "\n".join(str(i) for i in range(1, n + 1)))
        gutter.config(state=tk.DISABLED)

    def _set_state(self, state: str):
        if state == "idle":
            self.btn_run.config(state=tk.NORMAL)
            self.btn_save.config(state=tk.DISABLED)
            self.btn_open.config(state=tk.DISABLED)
        elif state == "ready":
            self.btn_run.config(state=tk.NORMAL)
            self.btn_save.config(state=tk.NORMAL)
            self.btn_open.config(state=tk.DISABLED)
        elif state == "saved":
            self.btn_run.config(state=tk.NORMAL)
            self.btn_save.config(state=tk.NORMAL)
            self.btn_open.config(state=tk.NORMAL)
        elif state == "busy":
            self.btn_run.config(state=tk.DISABLED)
            self.btn_save.config(state=tk.DISABLED)
            self.btn_open.config(state=tk.DISABLED)
            self.root.config(cursor="watch")

    # --------------------------------------------------------------- обработчики
    def on_select_file(self):
        path = filedialog.askopenfilename(
            title="Выбрать документ",
            filetypes=[
                ("Документы", "*.pdf *.docx *.doc *.txt *.xlsx"),
                ("PDF", "*.pdf"),
                ("Word", "*.docx *.doc"),
                ("Текст", "*.txt"),
                ("Excel", "*.xlsx"),
                ("Все файлы", "*.*"),
            ],
        )
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() not in config.SUPPORTED_EXTS:
            messagebox.showerror("Не поддерживается", f"Формат {p.suffix} не поддерживается.")
            return
        self.source_path = p
        self.file_label.config(text=str(p))
        self.content = None
        self.last_out_path = None
        self.before_text.delete("1.0", tk.END)
        self.after_text.delete("1.0", tk.END)
        self._update_gutter(self.before_text)
        self._update_gutter(self.after_text)
        self.review_tree.delete(*self.review_tree.get_children())
        self.btn_ignore.config(state=tk.DISABLED)
        self.btn_open_review.config(state=tk.DISABLED)
        self._clear_selection()
        self.status.config(text="файл выбран, нажмите «Анонимизировать»")
        self._set_state("idle")

    def on_anonymize(self):
        if not self.source_path:
            return
        self._set_state("busy")
        self.status.config(text="обработка…")
        # В потоке, чтобы UI не зависал на больших PDF/Excel.
        threading.Thread(target=self._worker_anonymize, daemon=True).start()

    def _worker_anonymize(self):
        try:
            content = extractors.extract(self.source_path)
            before = writers.build_original_text(content)
            if isinstance(content, extractors.ExcelContent):
                after = writers.build_excel_text(content, self.mapper)
            else:
                after, _manifest = writers.build_document_text(content, self.mapper)
            review = writers.collect_review_candidates(content, self.mapper)
            self.root.after(0, self._show_preview, content, before, after, review)
        except Exception as e:
            self.root.after(0, self._fail, str(e))

    @staticmethod
    def _fmt_loc(loc: dict) -> str:
        if "cell" in loc:
            return f"{loc.get('sheet', '')}!{loc['cell']}"
        if "block_index" in loc:
            r = loc.get("row")
            return f"блок {loc['block_index']}" + (f", стр.{r}" if r is not None else "")
        return ""

    def _show_preview(self, content, before, after, review):
        self.content = content
        self.root.config(cursor="")
        self.before_text.delete("1.0", tk.END)
        self.after_text.delete("1.0", tk.END)
        self.before_text.insert(tk.END, "\n".join(before))
        self.after_text.insert(tk.END, "\n".join(after))
        # Номера строк слева — чтобы сопоставлять «до» и «после» построчно.
        self._update_gutter(self.before_text)
        self._update_gutter(self.after_text)
        # Подсветка псевдонимов в правой панели.
        self._highlight_pseudonyms(self.after_text)
        # Ревью-кандидаты.
        self.review_tree.delete(*self.review_tree.get_children())
        cands = review.get("candidates", []) if review else []
        for c in cands:
            locs = ", ".join(self._fmt_loc(l) for l in c.get("locations", [])[:3])
            self.review_tree.insert("", tk.END, values=(
                c["value"], c["type_guess"], c["reason"], c["count"], locs,
            ))
        # Подсветка кандидатов красным в обеих панелях предпросмотра.
        self._highlight_candidates(self.before_text, cands)
        self._highlight_candidates(self.after_text, cands)
        # Текст панелей обновился — сбрасываем навигацию по вхождениям.
        self._clear_selection()
        stats = self.mapper.stats()
        total = sum(stats.values())
        summary = ", ".join(f"{t}: {n}" for t, n in sorted(stats.items())) if stats else "ничего не найдено"
        n_rev = len(cands)
        rev_tag = f" | ревью: {n_rev}" + (" (см. _review.json)" if n_rev else "")
        self.status.config(text=f"замен: {total} ({summary}){rev_tag}")
        self.btn_open_review.config(state=tk.NORMAL if n_rev else tk.DISABLED)
        self._set_state("ready")

    def _fail(self, msg):
        self.root.config(cursor="")
        self._set_state("idle")
        self.status.config(text="ошибка")
        messagebox.showerror("Ошибка", msg)

    def _on_review_select(self, _event=None):
        sel = self.review_tree.selection()
        self.btn_ignore.config(state=tk.NORMAL if sel else tk.DISABLED)
        if sel:
            value = str(self.review_tree.item(sel[0])["values"][0])
            self._set_selection(value)
        else:
            self._clear_selection()

    def _set_selection(self, value: str) -> None:
        """Собрать все вхождения значения кандидата в обеих панелях,
        подсветить первое и включить навигацию."""
        value = value.strip()
        self._sel_value = value or None
        self._sel_positions = {}
        self._sel_index = {}
        if not value:
            self._disable_nav()
            return
        for widget in (self.before_text, self.after_text):
            widget.tag_remove("sel-cand", "1.0", tk.END)
            text = widget.get("1.0", tk.END)
            positions = []
            start = 0
            while True:
                idx = text.find(value, start)
                if idx == -1:
                    break
                positions.append(idx)
                start = idx + len(value)
            self._sel_positions[widget] = positions
            self._sel_index[widget] = 0
            self._show_sel(widget)
        total = max((len(p) for p in self._sel_positions.values()), default=0)
        nav = tk.NORMAL if total > 1 else tk.DISABLED
        self.btn_prev.config(state=nav)
        self.btn_next.config(state=nav)

    def _clear_selection(self) -> None:
        self._sel_value = None
        self._sel_positions = {}
        self._sel_index = {}
        for widget in (self.before_text, self.after_text):
            widget.tag_remove("sel-cand", "1.0", tk.END)
        self._disable_nav()

    def _disable_nav(self) -> None:
        self.btn_prev.config(state=tk.DISABLED)
        self.btn_next.config(state=tk.DISABLED)

    def _show_sel(self, widget) -> None:
        """Подсветить текущее вхождение и прокрутить к нему."""
        positions = self._sel_positions.get(widget, [])
        i = self._sel_index.get(widget, 0)
        value = self._sel_value
        if not positions or not value:
            return
        idx = positions[i]
        text = widget.get("1.0", tk.END)
        s = self._offset_to_index(text, idx)
        e = self._offset_to_index(text, idx + len(value))
        widget.tag_remove("sel-cand", "1.0", tk.END)
        widget.tag_add("sel-cand", s, e)
        widget.see(s)

    def on_prev_candidate(self):
        self._step_candidate(-1)

    def on_next_candidate(self):
        self._step_candidate(1)

    def _step_candidate(self, direction: int) -> None:
        if not self._sel_value:
            return
        for widget in (self.before_text, self.after_text):
            positions = self._sel_positions.get(widget, [])
            n = len(positions)
            if n < 2:
                continue
            i = (self._sel_index[widget] + direction) % n
            self._sel_index[widget] = i
            self._show_sel(widget)

    def on_ignore(self):
        """Добавить выбранное значение в dictionaries/ignore.txt (white-list)
        и убрать из списка кандидатов. Кеш детектора сбрасывается."""
        sel = self.review_tree.selection()
        if not sel:
            return
        value = self.review_tree.item(sel[0])["values"][0]
        config.IGNORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with config.IGNORE_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{value}\n")
        if hasattr(load_ignore, "_cache"):
            del load_ignore._cache
        self.review_tree.delete(sel[0])
        self.btn_ignore.config(state=tk.DISABLED)

    def on_open_review(self):
        if not self.source_path:
            return
        out_dir = config.output_dir(self.source_path)
        stem = f"{self.source_path.stem}_anon"
        review_path = out_dir / f"{stem}_review.json"
        # На этапе предпросмотра _review.json ещё не записан — генерируем его
        # на лету из текущего content, чтобы кнопка работала без «Сохранить».
        if not review_path.exists() and self.content is not None:
            review_path = writers.write_review_file(self.content, out_dir, stem, self.mapper)
        if review_path and review_path.exists():
            os.startfile(review_path)
        else:
            messagebox.showinfo(
                "Нет кандидатов",
                "Ревью-кандидаты не найдены — файл _review.json не создан.",
            )

    def _highlight_pseudonyms(self, widget: tk.Text):
        text = widget.get("1.0", tk.END)
        for m in _PSEUDO_RE.finditer(text):
            # перевести смещение в индексы Tk (строка.столбец)
            start = self._offset_to_index(text, m.start())
            end = self._offset_to_index(text, m.end())
            widget.tag_add("pseudo", start, end)

    def _highlight_candidates(self, widget: tk.Text, cands: list) -> None:
        """Подсветить значения ревью-кандидатов красным (все вхождения)."""
        if not cands:
            return
        text = widget.get("1.0", tk.END)
        # Сортируем по убыванию длины: длинные значения приоритетнее,
        # чтобы подсветка не «откусила» часть более длинного совпадения.
        vals = sorted({str(c.get("value", "")).strip() for c in cands}, key=len, reverse=True)
        for val in vals:
            if not val:
                continue
            start = 0
            while True:
                idx = text.find(val, start)
                if idx == -1:
                    break
                s = self._offset_to_index(text, idx)
                e = self._offset_to_index(text, idx + len(val))
                widget.tag_add("cand", s, e)
                start = idx + len(val)

    @staticmethod
    def _offset_to_index(text: str, offset: int) -> str:
        line = text.count("\n", 0, offset) + 1
        last_nl = text.rfind("\n", 0, offset)
        col = offset - (last_nl + 1)
        return f"{line}.{col}"

    def on_save(self):
        if self.content is None:
            return
        try:
            src = self.source_path
            out_name = f"{src.stem}_anon.md"
            out_dir = config.output_dir(src)
            out_path = writers.write_content(self.content, out_dir, self.mapper, out_name)
            self.mapper.save()
            self.last_out_path = out_path
            self.status.config(text=f"сохранено: {out_path}")
            self._set_state("saved")
        except Exception as e:
            messagebox.showerror("Ошибка сохранения", str(e))
            self.status.config(text="ошибка сохранения")

    def on_open_folder(self):
        if self.last_out_path and self.last_out_path.exists():
            # Открываем проводник с выделением файла (Windows).
            os.system(f'explorer /select,"{self.last_out_path}"')
        elif self.source_path:
            os.startfile(self.source_path.parent)


def main():
    root = tk.Tk()
    AnonymizeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()