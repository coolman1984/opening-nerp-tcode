"""Which G-MES a run talks to (HISTORY.md Phase 130).

Samsung runs more than one G-MES. The tool was built against one - SEEG's own,
`seegmes4` - and the HQ one (`gmes4`, "MES_HQ") lists several factories in one tree
(SEEG-P, SEH-P, SEHC, ...): the benchmark reports compare SEEG-P with those, so they
are pulled from HQ. The same account signs in to both through AD SSO.

A site is two things and nothing else:

    the address    the page the browser opens, and the host a tab must be on to count
                   as G-MES (`gmes_common.is_gmes_page`)
    its data       its own recordings, batches, record checks and confirmations - the
                   SAME layout, one level down:

        SEEG (the default)   screens/            screens/batches/   screens/certificates/
        HQ                   sites/hq/screens/   sites/hq/screens/batches/   ...

A screen code means a different screen on each site (P1112UM00 on HQ lists other
factories and other columns), so one site's recording must never be replayed on the
other. Keeping each site's data in its own folder makes that impossible by
construction, and lets everything that reads `gmes_profile.SCREENS_DIR` - replay,
batches, the record check, the twin sync - work unchanged.

Chosen per process: `--site hq` on `gmes_report.py` / `gmes_batch.py`, or the
GMES_SITE environment variable (a child process inherits it; a scheduled launcher
passes `--site`). One browser serves both: it holds each site's session cookie, and
the run lock still allows one run at a time.
"""
import os
from urllib.parse import urlsplit

ENV = "GMES_SITE"
DEFAULT = "seeg"

SITES = {
    "seeg": {"url": "http://seegmes4.sec.samsung.net/mes4/sm/nexacro/index_ext_2318.html",
             "label": "SEEG G-MES"},
    "hq": {"url": "http://gmes4.sec.samsung.net/mes4/sm/nexacro/index_2318.html",
           "label": "HQ G-MES (MES_HQ)"},
}

#: The site this process is pointed at - set by `activate()`.
ACTIVE = None

# The default site's paths as the front end left them (the window moves them into its
# own data folder first), captured on the first activate() so a later switch back to
# the default site restores exactly them.
_BASE = None


def normalise(name):
    """'HQ ' -> 'hq'; '' / None -> the default. An unknown name is refused - a typo
    must never quietly mean SEEG."""
    key = (name or "").strip().lower() or DEFAULT
    if key not in SITES:
        raise ValueError(f"unknown G-MES site {name!r} - use one of: {', '.join(SITES)}")
    return key


def requested():
    """The site named by the environment (GMES_SITE), else the default."""
    return normalise(os.environ.get(ENV))


def current():
    return ACTIVE or requested()


def url(site=None):
    return SITES[normalise(site or current())]["url"]


def host(site=None):
    return urlsplit(url(site)).hostname.lower()


def label(site=None):
    return SITES[normalise(site or current())]["label"]


def is_default(site=None):
    return normalise(site or current()) == DEFAULT


def task_suffix(site=None):
    """'' for the default site, '.hq' for HQ. A batch name cannot contain a dot, so a
    task name ending in one names its site without any ambiguity (gmes_schedule)."""
    site = normalise(site or current())
    return "" if site == DEFAULT else "." + site


def split_task_suffix(name):
    """'weekly.hq' -> ('weekly', 'hq'); 'weekly' -> ('weekly', 'seeg')."""
    stem, dot, tail = name.rpartition(".")
    if dot and tail.lower() in SITES and tail.lower() != DEFAULT:
        return stem, tail.lower()
    return name, DEFAULT


def site_root(data_root, site=None):
    """Where a site's data lives under a front end's data root (the project folder,
    or the window's data folder)."""
    site = normalise(site or current())
    return data_root if site == DEFAULT else os.path.join(data_root, "sites", site)


def known_sites(data_root):
    """Every non-default site that has a data folder under `data_root`."""
    base = os.path.join(data_root, "sites")
    try:
        names = os.listdir(base)
    except OSError:
        return []
    return [n for n in sorted(names) if n in SITES and n != DEFAULT
            and os.path.isdir(os.path.join(base, n))]


def activate(site=None):
    """Point this process at `site`: the G-MES address and every data folder.

    Safe to call again with another site (the window switches): the default site's
    paths are captured the first time and restored from that capture. Returns the
    site's key."""
    global ACTIVE, _BASE
    site = normalise(site if site is not None else requested())
    import gmes_batch
    import gmes_common
    import gmes_profile
    import gmes_recordcheck
    on_other_site = ACTIVE not in (None, DEFAULT)
    if not on_other_site:
        # Captured fresh each time we leave the default site: whatever the front end
        # (or a test) has pointed the default paths at by now is what a switch back
        # must restore - never a capture from earlier in the process.
        _BASE = {"screens": gmes_profile.SCREENS_DIR, "shipped": gmes_profile.SHIPPED_DIR,
                 "batches": gmes_batch.BATCH_DIR, "certs": gmes_recordcheck.CERT_DIR,
                 "confirm": gmes_recordcheck.CONFIRM_DIR}
    if site == DEFAULT and not on_other_site:
        pass                              # already there: the paths are left as they are
    elif site == DEFAULT:
        gmes_profile.SCREENS_DIR = _BASE["screens"]
        gmes_profile.SHIPPED_DIR = _BASE["shipped"]
        gmes_batch.BATCH_DIR = _BASE["batches"]
        gmes_recordcheck.CERT_DIR = _BASE["certs"]
        gmes_recordcheck.CONFIRM_DIR = _BASE["confirm"]
    else:
        # The data root is the folder that holds the default `screens` folder: the
        # project on the command line, GMES/data in the window.
        root = site_root(os.path.dirname(_BASE["screens"]), site)
        gmes_profile.SCREENS_DIR = os.path.join(root, "screens")
        # Shipped screen structures were learned on SEEG's G-MES. Another site's
        # screen with the same code is a different screen, so nothing is shipped for it.
        gmes_profile.SHIPPED_DIR = os.path.join(root, "screens_known")
        gmes_batch.BATCH_DIR = os.path.join(root, "screens", "batches")
        # The window keeps certificates beside its screens folder, the command line
        # inside it; each keeps that same shape for the site.
        gmes_recordcheck.CERT_DIR = os.path.join(root, "certificates") if _BASE["certs"] else None
        gmes_recordcheck.CONFIRM_DIR = root if _BASE["confirm"] else None
    gmes_common.GMES_URL = SITES[site]["url"]
    gmes_common.GMES_HOST = host(site)
    os.environ[ENV] = site            # child processes (a batch's own runs) follow
    ACTIVE = site
    return site


def take_site_argument(argv):
    """Remove `--site X` / `--site=X` from an argument list and return (site, rest).

    The entrances read it before their own parser runs, because the site decides
    which recordings and batches the parser's own defaults and checks look at."""
    rest, site, i = [], None, 0
    argv = list(argv)
    while i < len(argv):
        a = argv[i]
        if a == "--site":
            if i + 1 >= len(argv):
                raise ValueError("--site needs a name: " + ", ".join(SITES))
            site = argv[i + 1]
            i += 2
            continue
        if a.startswith("--site="):
            site = a.split("=", 1)[1]
            i += 1
            continue
        rest.append(a)
        i += 1
    return (normalise(site) if site is not None else None), rest
