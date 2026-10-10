"""Plugin lifecycle: toolbar, menu entries and the timeline dock."""

from __future__ import annotations

import os
from typing import List, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.core import Qgis, QgsApplication

try:  # PyQt5 keeps QAction in QtWidgets, PyQt6 moved it to QtGui
    from qgis.PyQt.QtWidgets import QAction
except ImportError:  # pragma: no cover
    from qgis.PyQt.QtGui import QAction

from .attribution import AttributionOverlay
from .dock_widget import TimelineDockWidget
from .layers import WaybackLayerManager
from .network import WaybackNetworkFix
from .wmts_loader import WaybackCatalogService

MENU_TITLE = "&Wayback Explorer"
MESSAGE_TITLE = "Wayback Explorer"


class WaybackExplorerPlugin:
    """Wires the catalog service, layer manager and timeline dock into QGIS."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.actions: List[QAction] = []
        self.toolbar = None
        self.catalog: Optional[WaybackCatalogService] = None
        self.layer_manager: Optional[WaybackLayerManager] = None
        self.timeline_dock: Optional[TimelineDockWidget] = None
        self.network_fix = WaybackNetworkFix()
        self.attribution: Optional[AttributionOverlay] = None

    def _own_icon(self) -> QIcon:
        return QIcon(os.path.join(self.plugin_dir, "icon.svg"))

    # ------------------------------------------------------------- lifecycle
    def initGui(self) -> None:  # noqa: N802 - name mandated by QGIS
        main_window = self.iface.mainWindow()

        if not self.network_fix.install():
            self.iface.messageBar().pushMessage(
                MESSAGE_TITLE,
                "This QGIS version has no network request preprocessor (needs QGIS 3.22+); "
                "redirected Wayback tiles may render blank.",
                Qgis.MessageLevel.Warning, 10,
            )

        self.catalog = WaybackCatalogService()
        self.layer_manager = WaybackLayerManager(self.catalog.capabilities_url)
        self.attribution = AttributionOverlay(self.iface.mapCanvas())

        self.timeline_dock = TimelineDockWidget(self.iface, self.catalog, self.layer_manager, main_window)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.timeline_dock)
        self.timeline_dock.hide()

        self.toolbar = self.iface.addToolBar("Wayback Explorer")
        self.toolbar.setObjectName("WaybackExplorerToolbar")

        timeline_action = self.timeline_dock.toggleViewAction()
        timeline_action.setIcon(self._own_icon())
        timeline_action.setText("Wayback Timeline")
        timeline_action.setToolTip("Show or hide the Wayback timeline dock")

        refresh_action = QAction(QgsApplication.getThemeIcon("/mActionRefresh.svg"),
                                 "Refresh Wayback Catalog", main_window)
        refresh_action.setToolTip("Reload the list of Wayback releases from Esri")
        refresh_action.triggered.connect(self.catalog.fetch)

        for action in (timeline_action, refresh_action):
            self.toolbar.addAction(action)
            self.iface.addPluginToWebMenu(MENU_TITLE, action)
            self.actions.append(action)

        self.catalog.failed.connect(self._on_catalog_failed)
        self.catalog.loaded.connect(self._on_catalog_loaded)

    def unload(self) -> None:
        if self.catalog is not None:
            self.catalog.cancel()
        if self.attribution is not None:
            self.attribution.shutdown()
            self.attribution = None

        for action in self.actions:
            self.iface.removePluginWebMenu(MENU_TITLE, action)
            if self.toolbar is not None:
                self.toolbar.removeAction(action)
        self.actions = []

        if self.toolbar is not None:
            self.iface.mainWindow().removeToolBar(self.toolbar)
            self.toolbar.deleteLater()
            self.toolbar = None

        if self.timeline_dock is not None:
            self.iface.removeDockWidget(self.timeline_dock)
            self.timeline_dock.deleteLater()
            self.timeline_dock = None

        self.layer_manager = None
        self.catalog = None
        self.network_fix.remove()

    # ----------------------------------------------------------------- slots
    def _on_catalog_failed(self, message: str) -> None:
        self.iface.messageBar().pushMessage(MESSAGE_TITLE, message, Qgis.MessageLevel.Warning, 10)

    def _on_catalog_loaded(self, releases: list) -> None:
        if releases:
            self.iface.mainWindow().statusBar().showMessage(
                f"Wayback catalog loaded: {len(releases)} releases "
                f"({releases[0].label} to {releases[-1].label})", 5000
            )
