# Click-To-Open Top-Bar Menus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The top bar's `File` and `Run batch` dropdowns open only on click, stay open regardless of pointer position, hover-switch between each other while one is open, and close only on an outside click — standard menu-bar semantics.

**Architecture:** StarPost's frameless main window has a single top bar whose two dropdown buttons use custom classes in `src/starpost/gui/widgets.py`: `HoverMenuToolButton` (opens its menu on mouse-enter) and `HoverMenu` (auto-closes when the pointer strays). Task 1 inverts the behavior in place: delete the hover-open override (the buttons' `InstantPopup` mode already opens on click natively), delete all auto-close logic, add a hover-switch handoff (the open menu holds the mouse grab, sees the pointer cross a sibling menu button, closes itself, and defers opening that button's menu), and relocate the stuck-hover-outline fix to the menu's `hideEvent`. Task 2 renames the classes (`HoverMenu` → `BarMenu`, `HoverMenuToolButton` → `BarMenuButton`) so the names match the new semantics.

**Tech Stack:** Python 3.11, PySide6, pytest.

**Spec:** `docs/superpowers/specs/2026-07-12-click-to-open-menus-design.md`

## Global Constraints

- Run the *full* suite only via `python scripts/run_tests.py` (per-file process isolation; a bare full-suite `pytest` hangs). Single-file pytest runs are fine directly.
- On a headless machine, prefix every pytest/run_tests command with `QT_QPA_PLATFORM=offscreen `.
- Lint with `ruff check .` (line-length 100, py311 target) before each commit.
- Commit after every task; user-facing changes go in `CHANGELOG.md` under `## [Unreleased]`, existing style.
- Menus must dismiss on outside click via native QMenu popup behavior — do NOT implement any custom outside-click handling, and do NOT reintroduce any pointer-position auto-close.
- Never call the real `QToolButton.showMenu()` in a test — it blocks until the menu is dismissed; monkeypatch it and assert on recorded calls.

---

### Task 1: Menu-bar semantics in the existing classes

Behavior change only — class names stay `HoverMenu` / `HoverMenuToolButton` until Task 2.

**Files:**
- Modify: `src/starpost/gui/widgets.py` (imports ~line 4-11; `HoverMenu` at ~313-387; `HoverMenuToolButton` at ~390-413)
- Modify: `src/starpost/gui/main_window.py` (one stale comment line in `_build_toolbar`, ~line 412)
- Modify: `CHANGELOG.md` (the `## [Unreleased]` section at the top)
- Test: `tests/test_widgets.py` (helpers ~line 187-216, hover tests ~line 219-375), `tests/test_main_window.py` (delete one test at ~line 2406-2432)

**Interfaces:**
- Consumes: existing `HoverMenu(parent, owner=..., sibling_bar=...)` constructor (signature unchanged), existing `HoverMenuToolButton._clear_stuck_hover()` (kept verbatim), existing test helper `_move_to(menu, global_pt)` in `tests/test_widgets.py` (kept).
- Produces: `HoverMenu.mouseMoveEvent` performs only the hover-switch handoff; `HoverMenu.hideEvent` clears the owner's stuck hover; `HoverMenuToolButton` has NO `enterEvent` override and no other behavior beyond `_clear_stuck_hover`. Task 2 renames these classes but changes no behavior.

- [ ] **Step 1: Replace the six obsolete hover tests with the new behavior tests**

In `tests/test_widgets.py`:

1. DELETE the helper `_shown_hover_menu` (~lines 204-216) and these six tests (~lines 219-375): `test_hover_menu_closes_when_pointer_strays_far`, `test_hover_menu_stays_open_within_margin`, `test_hover_menu_closes_when_moving_onto_sibling_bar`, `test_hover_menu_sibling_bar_does_not_close_over_owner`, `test_hover_menu_stays_open_over_visible_submenu`, `test_hover_menu_closes_when_submenu_hidden`. Keep `_move_to` (~lines 187-201).

2. In their place (after `_move_to`, before `test_enable_range_selection_sets_extended`), add:

```python
def _shown_bar_menu():
    """A menu button on a bar with its menu open — the starting state for the
    stays-open and hover-switch tests. The bar is positioned but not shown
    (child mapToGlobal works without showing); only the menu is shown."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QWidget

    from starpost.gui.widgets import HoverMenu, HoverMenuToolButton

    bar = QWidget()
    bar.setGeometry(QRect(0, 0, 400, 30))
    btn = HoverMenuToolButton(bar)
    btn.setGeometry(QRect(0, 0, 80, 30))
    menu = HoverMenu(btn, owner=btn, sibling_bar=bar)
    menu.addAction("A")
    menu.setGeometry(QRect(200, 200, 120, 60))
    menu.show()
    return bar, btn, menu


def _other_menu_button(bar):
    """A second menu button on ``bar`` — a hover-switch handoff target."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QMenu

    from starpost.gui.widgets import HoverMenuToolButton

    other = HoverMenuToolButton(bar)
    other.setGeometry(QRect(100, 0, 80, 30))
    other_menu = QMenu(other)
    other_menu.addAction("B")
    other.setMenu(other_menu)
    return other


def test_bar_menu_stays_open_when_pointer_strays_far(app):
    """Moving the pointer far away leaves the menu open — it only dismisses on
    a click (native popup behaviour); there is no distance-based auto-close."""
    from PySide6.QtCore import QPointF

    bar, btn, menu = _shown_bar_menu()  # noqa: F841 (keep btn alive)
    _move_to(menu, QPointF(5000, 5000))
    assert menu.isVisible()
    bar.deleteLater()


def test_bar_menu_stays_open_over_sibling_bar(app):
    """The pointer crossing the bar's empty area (or its non-menu items) keeps
    the menu open — only another *menu* button is a handoff target."""
    from PySide6.QtCore import QPointF

    bar, btn, menu = _shown_bar_menu()  # noqa: F841 (keep btn alive)
    _move_to(menu, QPointF(300, 15))  # on the bar, away from any menu button
    assert menu.isVisible()
    bar.deleteLater()


def test_bar_menu_hands_off_to_other_menu_button(app, monkeypatch):
    """With a menu open, hovering a different menu button on the bar closes
    this menu and opens that button's menu without a click."""
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication

    bar, btn, menu = _shown_bar_menu()  # noqa: F841 (keep btn alive)
    other = _other_menu_button(bar)
    calls = []
    monkeypatch.setattr(other, "showMenu", lambda: calls.append(1))

    _move_to(menu, QPointF(140, 15))  # inside `other`
    assert not menu.isVisible()
    QApplication.processEvents()  # fire the deferred (singleShot) showMenu
    assert calls == [1]
    bar.deleteLater()


def test_bar_menu_handoff_skips_disabled_button(app, monkeypatch):
    """A disabled menu button (e.g. during a running batch) is not a handoff
    target — the open menu stays open and the disabled menu stays shut."""
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication

    bar, btn, menu = _shown_bar_menu()  # noqa: F841 (keep btn alive)
    other = _other_menu_button(bar)
    other.setEnabled(False)
    calls = []
    monkeypatch.setattr(other, "showMenu", lambda: calls.append(1))

    _move_to(menu, QPointF(140, 15))
    assert menu.isVisible()
    QApplication.processEvents()
    assert calls == []
    bar.deleteLater()


def test_bar_menu_button_hover_does_not_open(app, monkeypatch):
    """Hovering a menu button never opens its closed menu — opening is
    click-only (the button's InstantPopup mode, handled natively by Qt)."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent
    from PySide6.QtWidgets import QMenu

    from starpost.gui.widgets import HoverMenuToolButton

    btn = HoverMenuToolButton()
    menu = QMenu(btn)
    menu.addAction("A")
    btn.setMenu(menu)
    calls = []
    monkeypatch.setattr(btn, "showMenu", lambda: calls.append(1))
    btn.enterEvent(QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    assert calls == []
    btn.deleteLater()


def test_bar_menu_hide_clears_owner_stuck_hover(app, monkeypatch):
    """Closing the menu (any path: outside click, Esc, handoff) drops the owner
    button's leftover hover outline once the pointer has moved elsewhere — the
    menu's mouse grab swallowed the button's leave event."""
    from PySide6.QtCore import QPoint, Qt

    import starpost.gui.widgets as widgets

    bar, btn, menu = _shown_bar_menu()
    btn.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    monkeypatch.setattr(widgets.QCursor, "pos", staticmethod(lambda: QPoint(10000, 10000)))
    menu.hide()
    assert btn.testAttribute(Qt.WidgetAttribute.WA_UnderMouse) is False
    bar.deleteLater()
```

3. In `tests/test_main_window.py`, DELETE `test_hover_menu_tool_button_respects_disabled_state` (~lines 2406-2432 — it tests the removed `enterEvent` hover-open; the disabled-lockout concern is now covered by `test_bar_menu_handoff_skips_disabled_button` above). KEEP `test_hover_menu_tool_button_clears_leftover_hover` unchanged.

- [ ] **Step 2: Run the new tests to verify they fail against current behavior**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_widgets.py -v`
Expected: the six new `test_bar_menu_*` tests FAIL (`stays_open_when_pointer_strays_far` and `stays_open_over_sibling_bar` fail on `assert menu.isVisible()` — current code auto-closes; `hands_off_to_other_menu_button` fails on `assert calls == [1]` — no handoff exists; `handoff_skips_disabled_button` fails on `assert menu.isVisible()`; `button_hover_does_not_open` fails on `assert calls == []` — current enterEvent opens; `hide_clears_owner_stuck_hover` fails on the final attribute assert — nothing clears it on hide). The deleted tests no longer run. Pre-existing non-hover tests still pass.

- [ ] **Step 3: Rewrite the two widget classes**

In `src/starpost/gui/widgets.py`:

1. Add `QTimer` to the `PySide6.QtCore` import block (alphabetical position, after `Qt`):

```python
from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    Qt,
    QTimer,
)
```

2. Replace the entire `HoverMenu` class (docstring, `CLOSE_MARGIN`, `__init__`, `_global_rect`, `mouseMoveEvent`) with:

```python
class HoverMenu(QMenu):
    """A menu-bar-style dropdown for the top bar's menu buttons.

    Opened by clicking its :class:`HoverMenuToolButton` (via ``InstantPopup``),
    it behaves like a menu on a traditional menu bar: it stays open no matter
    where the pointer goes, and only a click anywhere else (or Esc) dismisses
    it — both native QMenu popup behaviours.

    While open it holds the mouse grab, so it — not the bar's buttons — sees
    the pointer crossing the bar. When the pointer lands on a *different*
    enabled menu button on ``sibling_bar``, the menu hands off: it closes and
    opens that button's menu, so the bar's dropdowns can be browsed with a
    single click, menu-bar style.
    """

    def __init__(
        self,
        parent=None,
        owner: QWidget | None = None,
        sibling_bar: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # The button the menu belongs to: skipped when scanning for handoff
        # targets, and cleared of its stuck hover outline when the menu hides.
        self._owner = owner
        # The bar holding the owner; its *other* menu buttons are hover-switch
        # handoff targets while this menu is open.
        self._sibling_bar = sibling_bar

    @staticmethod
    def _global_rect(w: QWidget) -> QRect:
        return QRect(w.mapToGlobal(w.rect().topLeft()), w.size())

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if self._sibling_bar is None:
            return
        pos = event.globalPosition().toPoint()
        for btn in self._sibling_bar.findChildren(HoverMenuToolButton):
            if (
                btn is not self._owner
                and btn.isEnabled()
                and btn.menu() is not None
                and self._global_rect(btn).contains(pos)
            ):
                # Hand off: close this menu, then open the hovered button's.
                # Deferred — showMenu blocks, so this close must unwind first.
                self.close()
                QTimer.singleShot(0, btn.showMenu)
                return

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        # The grab swallowed the owner's leave event; drop its stale hover
        # outline on every close path (outside click, Esc, handoff).
        if isinstance(self._owner, HoverMenuToolButton):
            self._owner._clear_stuck_hover()
```

3. Replace `HoverMenuToolButton` (delete `enterEvent`, keep `_clear_stuck_hover` verbatim):

```python
class HoverMenuToolButton(QToolButton):
    """A toolbar button for a :class:`HoverMenu` dropdown. Opens on click only
    (callers set ``InstantPopup``); hovering never opens a closed menu. Hover
    *does* switch menus while a sibling's menu is already open — that handoff
    lives in :class:`HoverMenu`, which holds the mouse grab at that point."""

    def _clear_stuck_hover(self) -> None:
        """After the popup closes, the button keeps its hover (auto-raise) outline:
        the menu grabbed the mouse, so no leaveEvent arrived to drop the mouse-over
        state. Clear it when the pointer is no longer over the button."""
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
            self.update()
```

4. In `src/starpost/gui/main_window.py` `_build_toolbar` (~line 412), the File-menu comment ends with "Hover-opens like Run batch." — replace that sentence so the comment reads:

```python
        # File menu: toolbar-level access to the Files tab's add dialogs and
        # the Data tab's portable-CSV import/export — same slots, second entry
        # point. Click-opens like Run batch.
```

- [ ] **Step 4: Run the widget and main-window tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_widgets.py tests/test_main_window.py -v`
Expected: ALL PASS (six new `test_bar_menu_*` tests green; `test_hover_menu_tool_button_clears_leftover_hover` still green; File-menu structure/wiring tests untouched and green).

- [ ] **Step 5: Update the changelog**

In `CHANGELOG.md`, the `## [Unreleased]` section currently holds one New Features bullet describing the File menu as "It hover-opens like Run batch and offers…". Replace the whole section with:

```markdown
## [Unreleased]

### New Features
- **File menu** — a new **File** dropdown sits first in the top bar (before
  Run batch), offering **Add ▸ Files… / Folder…** (the Files tab's add
  dialogs), **Import data…** and **Export data…** (the Data tab's
  portable-CSV import/export) — the same operations, reachable without
  switching tabs.

### Improvements
- **Menu-bar-style dropdowns** — the top bar's **File** and **Run batch**
  menus now open on click (no more hover-open) and stay open wherever the
  mouse goes; with one open, hovering the other menu button switches to it,
  and a click anywhere else dismisses it — like a traditional menu bar.
```

- [ ] **Step 6: Lint and commit**

```bash
ruff check .
git add src/starpost/gui/widgets.py src/starpost/gui/main_window.py tests/test_widgets.py tests/test_main_window.py CHANGELOG.md
git commit -m "Top-bar menus: click to open, hover-switch, dismiss on outside click"
```

---

### Task 2: Rename the classes to match the new semantics

`HoverMenu` → `BarMenu`, `HoverMenuToolButton` → `BarMenuButton`. Pure mechanical rename — zero behavior change. (The docstrings were already rewritten for the new semantics in Task 1; only the class names inside them change here.)

**Files:**
- Modify: `src/starpost/gui/widgets.py` (class definitions and every internal reference, including `:class:` docstring roles, the `findChildren(...)` call, and the `isinstance(...)` check)
- Modify: `src/starpost/gui/main_window.py` (the `from starpost.gui.widgets import HoverMenu, HoverMenuToolButton, UniformTabBar` line at ~43 and the four construction sites at ~415/423/439/448)
- Test: `tests/test_widgets.py`, `tests/test_main_window.py` (import/usage references; also rename the one remaining old-name test)

**Interfaces:**
- Consumes: Task 1's final class bodies (unchanged here).
- Produces: `BarMenu` (same constructor: `BarMenu(parent, owner=..., sibling_bar=...)`) and `BarMenuButton` exported from `starpost.gui.widgets`. The old names cease to exist — nothing keeps aliases.

- [ ] **Step 1: Rename every reference**

Across the four files, replace `HoverMenuToolButton` → `BarMenuButton` first, then `HoverMenu` → `BarMenu` (this order prevents the substring `HoverMenu` inside `HoverMenuToolButton` from being half-renamed):

```bash
sed -i 's/HoverMenuToolButton/BarMenuButton/g; s/HoverMenu/BarMenu/g' \
  src/starpost/gui/widgets.py src/starpost/gui/main_window.py \
  tests/test_widgets.py tests/test_main_window.py
```

Then rename the one test whose name still says "hover menu tool button": in `tests/test_main_window.py`, `test_hover_menu_tool_button_clears_leftover_hover` → `test_bar_menu_button_clears_leftover_hover` (its docstring already describes the behavior, not the class; leave it).

- [ ] **Step 2: Verify no old names remain**

Run: `grep -rn "HoverMenu" src/ tests/`
Expected: no output.

- [ ] **Step 3: Run the affected test files**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_widgets.py tests/test_main_window.py tests/test_gui_imports.py -v`
Expected: ALL PASS.

- [ ] **Step 4: Run the full suite and lint**

Run: `QT_QPA_PLATFORM=offscreen python scripts/run_tests.py`
Expected: full suite PASSES ("All files passed.").

Run: `ruff check .`
Expected: no findings.

- [ ] **Step 5: Commit**

```bash
git add src/starpost/gui/widgets.py src/starpost/gui/main_window.py tests/test_widgets.py tests/test_main_window.py
git commit -m "Widgets: rename HoverMenu/HoverMenuToolButton to BarMenu/BarMenuButton"
```
