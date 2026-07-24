"""The Hub — one window: dictation history, insights, dictionary, settings, account.

Minimal monochrome: deep charcoal surfaces, white/gray text, a single near-white
accent for the active nav item and chart highlight. No gradients, no color
beyond gray — everything here is 100% local (no network, no auth).

Settings is a page in this window, not a second window. The palette and the
stylesheet live in ``ui/theme.py`` so every page shares them.
"""

from datetime import datetime, timedelta, timezone

from PySide6 import QtCore, QtGui, QtWidgets

from rekounts.ui import theme
from rekounts.ui.branding import app_icon
from rekounts.ui.settings_page import SettingsPage
from rekounts.ui.theme import ACCENT, BORDER, TEXT, TEXT_3

_STYLE = theme.STYLE


def _local_dt(iso_ts: str) -> datetime:
    dt = datetime.fromisoformat(iso_ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def _day_label(d, today) -> str:
    if d == today:
        return "TODAY"
    if d == today - timedelta(days=1):
        return "YESTERDAY"
    return d.strftime("%A, %B %d").upper()


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


# ============================================================ Dictation page
class DictationPage(QtWidgets.QWidget):
    PAGE = 50

    def __init__(self, history):
        super().__init__()
        self.history = history
        self._offset = 0
        self._loaded = []
        self._query = ""

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(*theme.PAGE_MARGINS)
        root.setSpacing(14)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Dictation")
        title.setProperty("role", "page-title")
        header.addWidget(title)
        header.addStretch(1)
        clear = QtWidgets.QPushButton("Clear all")
        clear.setObjectName("Danger")
        clear.clicked.connect(self._clear_all)
        header.addWidget(clear)
        root.addLayout(header)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search your dictations…")
        self.search.textChanged.connect(self._on_search)
        root.addWidget(self.search)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        # Wrap cards to the viewport width instead of scrolling sideways.
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.container = QtWidgets.QWidget()
        self.vbox = QtWidgets.QVBoxLayout(self.container)
        self.vbox.setContentsMargins(0, 0, 8, 0)
        self.vbox.setSpacing(8)
        self.vbox.addStretch(1)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        self._offset = 0
        self._loaded = []
        if self._query:
            self._loaded = self.history.search(self._query)
        else:
            self._loaded = self.history.page(0, self.PAGE)
            self._offset = len(self._loaded)
        self._render()

    def _on_search(self, text):
        self._query = text.strip()
        self.refresh()

    def _load_more(self):
        more = self.history.page(self._offset, self.PAGE)
        self._offset += len(more)
        self._loaded.extend(more)
        self._render()

    def _render(self):
        _clear_layout(self.vbox)
        today = datetime.now().date()

        if not self._loaded:
            empty = QtWidgets.QLabel(
                "No dictations found." if self._query
                else "Nothing here yet. Hold your push-to-talk key and speak —\n"
                     "everything you dictate is saved locally, right here.")
            empty.setProperty("role", "hint")
            empty.setAlignment(QtCore.Qt.AlignCenter)
            self.vbox.addWidget(empty)
            self.vbox.addStretch(1)
            return

        last_day = None
        for entry in self._loaded:
            d = _local_dt(entry["timestamp"]).date()
            if d != last_day:
                last_day = d
                day = QtWidgets.QLabel(_day_label(d, today))
                day.setProperty("role", "day")
                self.vbox.addWidget(day)
            self.vbox.addWidget(self._entry_card(entry))

        if not self._query and self._offset < self.history.count():
            more = QtWidgets.QPushButton("Load more")
            more.setObjectName("Ghost")
            more.clicked.connect(self._load_more)
            self.vbox.addSpacing(4)
            self.vbox.addWidget(more, alignment=QtCore.Qt.AlignCenter)

        self.vbox.addStretch(1)

    def _entry_card(self, entry):
        card = QtWidgets.QWidget()
        card.setObjectName("Card")
        lay = QtWidgets.QHBoxLayout(card)
        lay.setContentsMargins(14, 12, 12, 12)
        lay.setSpacing(10)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(5)
        text = entry.get("cleaned_text") or entry.get("raw_text") or ""
        body = QtWidgets.QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        left.addWidget(body)

        meta_row = QtWidgets.QHBoxLayout()
        meta_row.setSpacing(8)
        t = _local_dt(entry["timestamp"]).strftime("%H:%M")
        dur = entry.get("duration_s") or 0
        meta = QtWidgets.QLabel(
            f"{t}  ·  {entry.get('word_count', 0)} words  ·  {dur:.1f}s")
        meta.setProperty("role", "meta")
        meta_row.addWidget(meta)
        # The entries users come hunting for: dictated but never pasted anywhere.
        if not entry.get("inserted", 1):
            badge = QtWidgets.QLabel("not pasted · saved here")
            badge.setProperty("role", "badge")
            meta_row.addWidget(badge)
        meta_row.addStretch(1)
        left.addLayout(meta_row)
        lay.addLayout(left, 1)

        btns = QtWidgets.QVBoxLayout()
        btns.setSpacing(6)
        copy = QtWidgets.QPushButton("Copy")
        copy.setObjectName("Ghost")
        copy.clicked.connect(lambda _=False, txt=text, b=copy: self._copy(txt, b))
        delete = QtWidgets.QPushButton("Delete")
        delete.setObjectName("Danger")
        delete.clicked.connect(lambda _=False, eid=entry["id"]: self._delete(eid))
        btns.addWidget(copy)
        btns.addWidget(delete)
        btns.addStretch(1)
        lay.addLayout(btns)
        return card

    def _copy(self, text, button):
        QtWidgets.QApplication.clipboard().setText(text)
        button.setText("Copied")
        QtCore.QTimer.singleShot(1200, lambda: button.setText("Copy"))

    def _delete(self, entry_id):
        self.history.delete(entry_id)
        self._loaded = [e for e in self._loaded if e["id"] != entry_id]
        self._render()

    def _clear_all(self):
        if not self.history.count():
            return
        ok = QtWidgets.QMessageBox.question(
            self, "Clear all history",
            "Permanently delete every saved dictation? This cannot be undone.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        if ok == QtWidgets.QMessageBox.Yes:
            self.history.clear_all()
            self.refresh()


# ============================================================== Insights page
class _BarChart(QtWidgets.QWidget):
    """Custom-painted daily-words bars — monochrome, no deps."""

    def __init__(self):
        super().__init__()
        self._data = []   # list[(date, words)]
        self.setMinimumHeight(180)

    def set_data(self, data):
        self._data = data
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if not self._data:
            return
        pad_b = 22          # room for a couple of date ticks
        top = 8
        avail_h = h - pad_b - top
        peak = max((v for _, v in self._data), default=0)
        n = len(self._data)
        gap = 4
        bar_w = max(2.0, (w - gap * (n - 1)) / n)
        today = datetime.now().date()

        # baseline
        p.setPen(QtGui.QPen(QtGui.QColor(BORDER), 1))
        p.drawLine(0, h - pad_b, w, h - pad_b)

        x = 0.0
        for d, v in self._data:
            bh = 0 if peak == 0 else (v / peak) * avail_h
            bh = max(bh, 2 if v > 0 else 0)
            y = (h - pad_b) - bh
            # today's bar in near-white; the rest in muted gray
            color = QtGui.QColor(ACCENT) if d == today else QtGui.QColor("#3c4049")
            if v == 0:
                color = QtGui.QColor("#24272e")   # faint stub for empty days
                bh = 2
                y = (h - pad_b) - bh
            p.setBrush(color)
            p.setPen(QtCore.Qt.NoPen)
            p.drawRoundedRect(QtCore.QRectF(x, y, bar_w, bh), 2, 2)
            x += bar_w + gap

        # sparse date ticks (first, middle, last)
        p.setPen(QtGui.QPen(QtGui.QColor(TEXT_3)))
        f = p.font(); f.setPointSize(8); p.setFont(f)
        for idx in {0, n // 2, n - 1}:
            d = self._data[idx][0]
            tx = idx * (bar_w + gap)
            p.drawText(QtCore.QRectF(tx - 12, h - pad_b + 4, 40, 16),
                       QtCore.Qt.AlignLeft, d.strftime("%b %d"))


class _StatCard(QtWidgets.QWidget):
    def __init__(self, label):
        super().__init__()
        self.setObjectName("StatCard")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)
        self.value = QtWidgets.QLabel("—")
        self.value.setStyleSheet(f"font-size: 26px; font-weight: 800; color: {TEXT};")
        cap = QtWidgets.QLabel(label)
        cap.setProperty("role", "meta")
        lay.addWidget(self.value)
        lay.addWidget(cap)

    def set_value(self, v):
        self.value.setText(str(v))


class InsightsPage(QtWidgets.QWidget):
    def __init__(self, history):
        super().__init__()
        self.history = history

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(*theme.PAGE_MARGINS)
        root.setSpacing(18)

        title = QtWidgets.QLabel("Insights")
        title.setProperty("role", "page-title")
        root.addWidget(title)

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(12)
        self.cards = {
            "words_today": _StatCard("Words today"),
            "words_7d": _StatCard("Words · 7 days"),
            "words_all": _StatCard("Words · all time"),
            "avg_wpm": _StatCard("Avg words / min"),
            "current_streak": _StatCard("Current streak"),
            "longest_streak": _StatCard("Longest streak"),
            "entries_all": _StatCard("Dictations"),
            "active_days": _StatCard("Active days"),
        }
        order = ["words_today", "words_7d", "words_all", "avg_wpm",
                 "current_streak", "longest_streak", "entries_all", "active_days"]
        for i, key in enumerate(order):
            grid.addWidget(self.cards[key], i // 4, i % 4)
        root.addLayout(grid)

        chart_wrap = QtWidgets.QWidget()
        chart_wrap.setObjectName("Card")
        cw = QtWidgets.QVBoxLayout(chart_wrap)
        cw.setContentsMargins(16, 14, 16, 12)
        cap = QtWidgets.QLabel("DAILY WORDS · LAST 3 WEEKS")
        cap.setProperty("role", "day")
        cw.addWidget(cap)
        self.chart = _BarChart()
        cw.addWidget(self.chart)
        root.addWidget(chart_wrap)
        root.addStretch(1)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        s = self.history.stats()
        for key, card in self.cards.items():
            v = s.get(key, 0)
            if key == "current_streak" or key == "longest_streak":
                v = f"{v} day" + ("" if v == 1 else "s")
            card.set_value(v)
        self.chart.set_data(self.history.daily_words(21))


# ============================================================= Dictionary page
class DictionaryPage(QtWidgets.QWidget):
    def __init__(self, history):
        super().__init__()
        self.history = history

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(*theme.PAGE_MARGINS)
        root.setSpacing(14)

        title = QtWidgets.QLabel("Dictionary")
        title.setProperty("role", "page-title")
        root.addWidget(title)
        hint = QtWidgets.QLabel(
            "Teach Rekounts names and jargon it keeps mishearing. "
            "The optional “sounds-like” spelling helps it recognize them. "
            "These words are passed to the recognizer as context, so they "
            "influence what it hears — they take effect on your next dictation.")
        hint.setWordWrap(True)
        hint.setProperty("role", "hint")
        root.addWidget(hint)

        add_row = QtWidgets.QHBoxLayout()
        add_row.setSpacing(8)
        self.word = QtWidgets.QLineEdit()
        self.word.setPlaceholderText("Word or phrase (e.g. Kubernetes)")
        self.sounds = QtWidgets.QLineEdit()
        self.sounds.setPlaceholderText("Sounds like (optional)")
        add_btn = QtWidgets.QPushButton("Add")
        add_btn.setObjectName("Ghost")
        add_btn.clicked.connect(self._add)
        self.word.returnPressed.connect(self._add)
        self.sounds.returnPressed.connect(self._add)
        add_row.addWidget(self.word, 2)
        add_row.addWidget(self.sounds, 2)
        add_row.addWidget(add_btn)
        root.addLayout(add_row)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.container = QtWidgets.QWidget()
        self.vbox = QtWidgets.QVBoxLayout(self.container)
        self.vbox.setContentsMargins(0, 0, 8, 0)
        self.vbox.setSpacing(8)
        self.vbox.addStretch(1)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def _add(self):
        if self.history.add_dictionary_word(self.word.text(), self.sounds.text()):
            self.word.clear()
            self.sounds.clear()
            self.refresh()

    def refresh(self):
        _clear_layout(self.vbox)
        words = self.history.dictionary_words()
        if not words:
            empty = QtWidgets.QLabel("No custom words yet.")
            empty.setProperty("role", "hint")
            empty.setAlignment(QtCore.Qt.AlignCenter)
            self.vbox.addWidget(empty)
            self.vbox.addStretch(1)
            return
        for entry in words:
            self.vbox.addWidget(self._word_row(entry))
        self.vbox.addStretch(1)

    def _word_row(self, entry):
        card = QtWidgets.QWidget()
        card.setObjectName("Card")
        lay = QtWidgets.QHBoxLayout(card)
        lay.setContentsMargins(14, 10, 12, 10)
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(2)
        w = QtWidgets.QLabel(entry["word"])
        w.setStyleSheet("font-weight: 600;")
        col.addWidget(w)
        if entry.get("sounds_like"):
            sl = QtWidgets.QLabel(f"sounds like “{entry['sounds_like']}”")
            sl.setProperty("role", "meta")
            col.addWidget(sl)
        lay.addLayout(col, 1)
        rm = QtWidgets.QPushButton("Remove")
        rm.setObjectName("Danger")
        rm.clicked.connect(lambda _=False, wid=entry["id"]: self._remove(wid))
        lay.addWidget(rm)
        return card

    def _remove(self, word_id):
        self.history.delete_dictionary_word(word_id)
        self.refresh()


# ================================================================= Account page
class AccountPage(QtWidgets.QWidget):
    def __init__(self, config, on_saved=None):
        super().__init__()
        self.config = config
        # Fired after the profile is saved so the Hub can render the new display
        # name in the sidebar — otherwise this page would be write-only.
        self._on_saved = on_saved or (lambda: None)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(*theme.PAGE_MARGINS)
        root.setSpacing(14)

        title = QtWidgets.QLabel("Account")
        title.setProperty("role", "page-title")
        root.addWidget(title)

        card = QtWidgets.QWidget()
        card.setObjectName("Card")
        form = QtWidgets.QVBoxLayout(card)
        form.setContentsMargins(18, 16, 18, 16)
        form.setSpacing(10)

        form.addWidget(self._label("Display name"))
        self.name = QtWidgets.QLineEdit(config.get("profile_display_name") or "")
        self.name.setPlaceholderText("Your name")
        form.addWidget(self.name)

        form.addWidget(self._label("Avatar image (optional)"))
        av_row = QtWidgets.QHBoxLayout()
        av_row.setSpacing(8)
        self.avatar = QtWidgets.QLineEdit(config.get("profile_avatar_path") or "")
        self.avatar.setPlaceholderText("Path to an image file")
        browse = QtWidgets.QPushButton("Browse…")
        browse.setObjectName("Ghost")
        browse.clicked.connect(self._browse)
        av_row.addWidget(self.avatar, 1)
        av_row.addWidget(browse)
        form.addLayout(av_row)

        save = QtWidgets.QPushButton("Save profile")
        save.setObjectName("Ghost")
        save.clicked.connect(self._save)
        form.addWidget(save, alignment=QtCore.Qt.AlignLeft)
        root.addWidget(card)

        note = QtWidgets.QLabel(
            "This is a local profile only — nothing leaves your machine. "
            "Cloud sign-in and sync come in a later release.")
        note.setWordWrap(True)
        note.setProperty("role", "hint")
        root.addWidget(note)
        root.addStretch(1)

    def _label(self, text):
        lbl = QtWidgets.QLabel(text)
        lbl.setProperty("role", "meta")
        return lbl

    def _browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose avatar image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif)")
        if path:
            self.avatar.setText(path)

    def _save(self):
        self.config.set("profile_display_name", self.name.text().strip())
        self.config.set("profile_avatar_path", self.avatar.text().strip())
        self.config.save()
        self._on_saved()


# ================================================================== Dashboard
class Dashboard(QtWidgets.QWidget):
    """The single app window. Inject the shared Config + History.

    ``on_settings_saved`` is called with no arguments after any settings change
    has been persisted — the app's live-apply hook. There is no second window
    and no restart path: changing a setting here changes the running app.
    """

    def __init__(self, config, history, on_settings_saved=None):
        super().__init__()
        self.config = config
        self.setObjectName("DashRoot")
        self.setWindowTitle("Rekounts")
        # Explicit, rather than relying on QApplication's default: the Hub is
        # also opened standalone by tools/demos that never set an app-wide icon.
        self.setWindowIcon(app_icon())
        self.setStyleSheet(_STYLE)
        self.resize(880, 620)
        self.setMinimumSize(720, 500)

        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- sidebar ---
        sidebar = QtWidgets.QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(196)
        sb = QtWidgets.QVBoxLayout(sidebar)
        sb.setContentsMargins(14, 20, 14, 16)
        sb.setSpacing(4)
        brand = QtWidgets.QLabel("Rekounts")
        brand.setProperty("role", "brand")
        brand.setContentsMargins(6, 0, 0, 12)
        sb.addWidget(brand)

        # Built now (before the pages) so AccountPage can call refresh_profile;
        # added to the sidebar as a footer further down.
        profile = self._build_sidebar_profile()

        self.stack = QtWidgets.QStackedWidget()
        # Production wires the real launch-at-login query/setter so the Settings
        # switch reflects a Task Manager disable; startup imports no Qt, so it is
        # safe here.
        from rekounts import startup as startup_mod
        self.settings = SettingsPage(
            config, history, on_saved=on_settings_saved,
            startup_setter=startup_mod.set_enabled,
            startup_getter=startup_mod.is_enabled)
        self.pages = [
            ("Dictation",  DictationPage(history)),
            ("Insights",   InsightsPage(history)),
            ("Dictionary", DictionaryPage(history)),
            ("Settings",   self.settings),
            ("Account",    AccountPage(config, on_saved=self.refresh_profile)),
        ]
        # Derived, not hard-coded, so reordering the nav can't break open_settings().
        self.settings_index = next(
            i for i, (_, page) in enumerate(self.pages) if page is self.settings)
        self._nav_group = QtWidgets.QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for i, (name, page) in enumerate(self.pages):
            self.stack.addWidget(page)
            btn = QtWidgets.QPushButton(name)
            btn.setObjectName("NavBtn")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, idx=i: self.stack.setCurrentIndex(idx))
            self._nav_group.addButton(btn, i)
            sb.addWidget(btn)
            if i == 0:
                btn.setChecked(True)
        sb.addStretch(1)
        sb.addWidget(profile)
        version = QtWidgets.QLabel("Local · Private")
        version.setProperty("role", "meta")
        sb.addWidget(version)

        outer.addWidget(sidebar)
        outer.addWidget(self.stack, 1)

    def show_page(self, index: int):
        self.stack.setCurrentIndex(index)
        btn = self._nav_group.button(index)
        if btn:
            btn.setChecked(True)

    def open_and_raise(self):
        """Bring the Hub to the front (used by the tray 'Open' action)."""
        self.show()
        self.raise_()
        self.activateWindow()

    def open_settings(self):
        """Open the Hub on the Settings page (the tray's 'Settings…' action)."""
        self.open_and_raise()
        self.show_page(self.settings_index)

    # ---------------------------------------------------------- sidebar profile
    def _build_sidebar_profile(self):
        """Sidebar footer showing the Account page's display name + avatar, so
        that page is honest — the name it saves is rendered somewhere instead of
        written and never read. Hidden until a display name is set."""
        wrap = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(wrap)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(9)
        self._avatar_label = QtWidgets.QLabel()
        self._avatar_label.setFixedSize(26, 26)
        self._name_label = QtWidgets.QLabel()
        self._name_label.setStyleSheet(
            f"color: {TEXT}; font-size: 12px; font-weight: 600;")
        row.addWidget(self._avatar_label, 0)
        row.addWidget(self._name_label, 1)
        self._profile_wrap = wrap
        self.refresh_profile()
        return wrap

    def refresh_profile(self):
        """Reflect profile_display_name / profile_avatar_path in the sidebar."""
        name = (self.config.get("profile_display_name") or "").strip()
        path = (self.config.get("profile_avatar_path") or "").strip()
        self._name_label.setText(name)
        pix = self._avatar_pixmap(path, name, 26)
        if pix is not None:
            self._avatar_label.setPixmap(pix)
            self._avatar_label.setVisible(True)
        else:
            self._avatar_label.clear()
            self._avatar_label.setVisible(False)
        # Nothing to show for a default (nameless) profile — keep the sidebar clean.
        self._profile_wrap.setVisible(bool(name))

    @staticmethod
    def _avatar_pixmap(path, name, size):
        if path:
            src = QtGui.QPixmap(path)
            if not src.isNull():
                return Dashboard._circular(src, size)
        if name:
            return Dashboard._monogram(name[0].upper(), size)
        return None

    @staticmethod
    def _circular(src, size):
        src = src.scaled(size, size, QtCore.Qt.KeepAspectRatioByExpanding,
                         QtCore.Qt.SmoothTransformation)
        out = QtGui.QPixmap(size, size)
        out.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(out)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        clip = QtGui.QPainterPath()
        clip.addEllipse(0, 0, size, size)
        p.setClipPath(clip)
        p.drawPixmap(int((size - src.width()) / 2),
                     int((size - src.height()) / 2), src)
        p.end()
        return out

    @staticmethod
    def _monogram(letter, size):
        out = QtGui.QPixmap(size, size)
        out.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(out)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtGui.QPen(QtGui.QColor(BORDER), 1))
        p.setBrush(QtGui.QColor(theme.CARD_HI))
        p.drawEllipse(0, 0, size - 1, size - 1)
        p.setPen(QtGui.QColor(TEXT))
        f = p.font()
        f.setPointSize(10)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QtCore.QRectF(0, 0, size, size), QtCore.Qt.AlignCenter, letter)
        p.end()
        return out

    # ------------------------------------------------------- live page refresh
    @QtCore.Slot(str, str, float, bool)
    def on_result_recorded(self, raw, cleaned, duration_s, inserted):
        """A dictation just finished (wired to Bridge.result, already marshaled
        to the GUI thread). If the visible page shows something the new entry
        changes, refresh it live instead of only on the next page switch."""
        current = self.stack.currentWidget()
        if isinstance(current, (DictationPage, InsightsPage)):
            try:
                current.refresh()
            except Exception:
                pass
