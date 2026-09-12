"""Choosing the result grid on a screen - pure logic, no browser.

Forked from gmes_core.py. `choose_grid` takes a ScreenInfo (see
screens/filters.py's docstring for why typed objects rather than dicts).
"""
import re


def digits_only(value):
    return re.sub(r"[^\d]", "", str(value or ""))


def choose_grid(info, prefer=None):
    """Pick the grid holding the report's rows, and say when the pick is a guess.

    The default is the biggest visible grid, which is right on a single-result
    screen and a coin toss on a master-detail one. A silent coin toss is
    exactly the failure this project keeps hitting, so when a second grid is
    comparable in size the choice is reported as ambiguous and the caller
    prints it. `prefer` (a grid or dataset name) settles it outright.

    Returns (grid, alternatives) - alternatives is empty when the pick is
    unambiguous. `grid`/each alternative is a GridRef."""
    grids = list(info.grids)
    if not grids:
        return None, []

    if prefer:
        p = prefer.strip().lower()
        for attr in ("dataset", "name"):
            exact = [g for g in grids if getattr(g, attr).lower() == p]
            if exact:
                return exact[0], []
        partial = [g for g in grids
                   if p in g.dataset.lower() or p in g.name.lower()]
        if len(partial) == 1:
            return partial[0], []
        if partial:
            return None, partial
        return None, grids

    visible = [g for g in grids if g.visible]
    # Sorted here as well as in the JS, so this function is correct on its own
    # terms rather than on an assumption about its caller.
    pool = sorted(visible or grids, key=lambda g: g.area, reverse=True)
    best = pool[0]
    rivals = [g for g in pool[1:] if g.area > best.area * 0.4]
    return best, rivals
