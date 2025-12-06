"""Prayers API package init.

Provides a convenience `load()` helper for the prayers database.

# pylint: disable=duplicate-code
"""

from osrsreboxed.prayers_api import all_prayers


def load() -> all_prayers.AllPrayers:
    """Load the prayers database.

    :return all_prayers: An AllPrayers object containing the entire prayer database.
    """
    return all_prayers.AllPrayers()
