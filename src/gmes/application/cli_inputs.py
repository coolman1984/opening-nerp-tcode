"""Validate CLI-shaped run requests before browser side effects begin."""
from ..contracts import RunSpec
from ..screens.filters import normalise_date


def _sets(items):
    values = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--set needs NAME=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        if not key.strip():
            raise ValueError("--set needs a non-empty name")
        values[key.strip()] = value.strip()
    return values


def _dates(date_from, date_to, date):
    from_value = normalise_date(date_from or date)
    to_value = normalise_date(date_to or date)
    if bool(from_value) != bool(to_value):
        raise ValueError("give both --from and --to, or --date for one day")
    return from_value, to_value


def _verified(value):
    if not value:
        return None
    column, sep, expected = value.partition("=")
    if not column.strip():
        raise ValueError("--verify needs COLUMN or COLUMN=VALUE")
    return column.strip(), expected.strip() if sep else None


def build_run_specs(screens, *, division=None, tree=None, date_from=None, date_to=None,
                    date=None, sets=(), options=(), grid=None, verify=None,
                    export="both", out_dir=None, dry_run=False, close_after=False,
                    use_profile=True):
    """Turn parsed values into typed runs without connecting to G-MES."""
    from_value, to_value = _dates(date_from, date_to, date)
    values, verification = _sets(sets), _verified(verify)
    return [RunSpec(screen_code=code, division=division, tree=tree,
                    date_from=from_value, date_to=to_value, sets=values,
                    options=tuple(options), grid_name=grid, verify=verification,
                    export=export, out_dir=out_dir, dry_run=dry_run,
                    close_after=close_after, use_profile=use_profile)
            for code in screens]
