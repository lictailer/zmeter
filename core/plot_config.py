"""Global pyqtgraph configuration for zmeter plots.

Image plots in ``core/all_plots.py`` expect row-major image arrays. This used
to be set as a side effect of importing ``core/scan_info.py``; it is now an
explicit call made when ``core.mainWindow`` and ``core.all_plots`` are
imported, so it is in effect whenever it was before.
"""

import pyqtgraph as pg


def configure_pyqtgraph():
    """Apply the pyqtgraph options zmeter relies on. Safe to call repeatedly."""
    pg.setConfigOptions(imageAxisOrder="row-major")
