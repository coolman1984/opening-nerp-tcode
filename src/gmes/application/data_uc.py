"""Dataset inspection use cases for presentation adapters."""
from ..query.dataset_reader import read_dataset, read_dataset_paged
from ..query.form_locator import list_forms


def list_open_forms(ws):
    """Return the open Nexacro forms and their datasets."""
    return list_forms(ws)


def read_open_dataset(ws, screen_code, dataset, *, limit=20, offset=0):
    """Read an explicitly bounded dataset through the query capability."""
    return read_dataset(ws, screen_code, dataset, limit=limit, offset=offset)


def read_dataset_pages(ws, screen_code, dataset, *, page_size=300):
    """Yield bounded dataset pages for a specialized external consumer."""
    return read_dataset_paged(ws, screen_code, dataset, page_size=page_size)
