"""Wayback Explorer - QGIS plugin entry point.

QGIS calls :func:`classFactory` with the ``QgisInterface`` instance and expects a
plugin object exposing ``initGui()`` and ``unload()``.
"""


def classFactory(iface):  # noqa: N802 - name mandated by QGIS
    """Instantiate the plugin for the running QGIS session."""
    from .plugin import WaybackExplorerPlugin

    return WaybackExplorerPlugin(iface)
