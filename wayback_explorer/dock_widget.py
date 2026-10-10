"""Timeline dock: slider + release dropdown + live-scrub / fixed-layer controls."""

from __future__ import annotations

from typing import List, Optional

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qgis.core import Qgis, QgsApplication, QgsProject
from qgis.gui import QgsDockWidget

from .catalog import (
    ESRI_ATTRIBUTION,
    ESRI_TERMS_URL,
    ESRI_WAYBACK_CREDIT,
    ESRI_WAYBACK_URL,
    WaybackRelease,
)
from .layers import LayerError, WaybackLayerManager
from .wmts_loader import WaybackCatalogService

MESSAGE_TITLE = "Wayback Explorer"
LIVE_DEBOUNCE_MS = 300


class TimelineDockWidget(QgsDockWidget):
    """Scrub through every Wayback release and push them into the project."""

    def __init__(self, iface, catalog: WaybackCatalogService, layer_manager: WaybackLayerManager,
                 parent: Optional[QWidget] = None):
        super().__init__("Wayback Timeline", parent)
        self.setObjectName("WaybackExplorerTimelineDock")
        self.iface = iface
        self.catalog = catalog
        self.layer_manager = layer_manager

        self._releases: List[WaybackRelease] = []
        self._updating = False

        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(LIVE_DEBOUNCE_MS)
        self._live_timer.timeout.connect(self._apply_live)

        self._build_ui()
        self._connect_signals()
        self._set_controls_enabled(False)
        if catalog.is_loaded:
            self._set_releases(catalog.releases)

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.status_label = QLabel("Catalog not loaded")
        self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.refresh_button = QToolButton()
        self.refresh_button.setIcon(QgsApplication.getThemeIcon("/mActionRefresh.svg"))
        self.refresh_button.setToolTip("Reload the Wayback release catalog")
        self.refresh_button.setAutoRaise(True)
        header.addWidget(self.status_label)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.date_label = QLabel("—")
        font = QFont(self.date_label.font())
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        self.date_label.setFont(font)
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.date_label)

        self.release_label = QLabel("")
        self.release_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.release_label)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setTracking(True)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(5)
        self.slider.setToolTip("Drag, use the arrow keys or the mouse wheel to move through releases")
        layout.addWidget(self.slider)

        bounds = QHBoxLayout()
        self.first_label = QLabel("")
        self.last_label = QLabel("")
        self.last_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        bounds.addWidget(self.first_label)
        bounds.addStretch()
        bounds.addWidget(self.last_label)
        layout.addLayout(bounds)

        self.combo = QComboBox()
        self.combo.setToolTip("Jump directly to a release")
        layout.addWidget(self.combo)

        actions = QHBoxLayout()
        self.live_check = QCheckBox("Live scrub layer")
        self.live_check.setToolTip(
            "Keep one layer in the project that follows the slider as you scrub"
        )
        self.add_fixed_button = QPushButton("Add Layer")
        self.add_fixed_button.setIcon(QgsApplication.getThemeIcon("/mActionAddWmsLayer.svg"))
        self.add_fixed_button.setToolTip("Add the selected release to the project as a WMTS layer")
        actions.addWidget(self.live_check)
        actions.addStretch()
        actions.addWidget(self.add_fixed_button)
        layout.addLayout(actions)

        notice = QLabel(
            f'<a href="{ESRI_WAYBACK_URL}">{ESRI_WAYBACK_CREDIT}</a>. {ESRI_ATTRIBUTION}.<br>'
            f'Imagery is streamed on demand and subject to the '
            f'<a href="{ESRI_TERMS_URL}">Esri Terms of Use</a>; '
            "nothing is bulk-downloaded or cached to disk."
        )
        notice.setWordWrap(True)
        notice.setOpenExternalLinks(True)
        notice.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        notice.setStyleSheet("color: palette(mid); font-size: 8pt;")
        layout.addWidget(notice)
        layout.addStretch()

        self.setWidget(container)

    def _connect_signals(self) -> None:
        self.catalog.loading_started.connect(self._on_loading_started)
        self.catalog.loaded.connect(self._on_loaded)
        self.catalog.failed.connect(self._on_failed)
        self.visibilityChanged.connect(self._on_visibility_changed)

        self.refresh_button.clicked.connect(self.catalog.fetch)
        self.slider.valueChanged.connect(self._on_slider_changed)
        self.slider.sliderReleased.connect(self._flush_live)
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        self.live_check.toggled.connect(self._on_live_toggled)
        self.add_fixed_button.clicked.connect(self._on_add_fixed)

        project = QgsProject.instance()
        project.layersRemoved.connect(self._on_layers_removed)
        project.cleared.connect(self._on_layers_removed)

    # -------------------------------------------------------------- catalog
    def current_release(self) -> Optional[WaybackRelease]:
        index = self.slider.value()
        if 0 <= index < len(self._releases):
            return self._releases[index]
        return None

    def select_release(self, release: WaybackRelease) -> None:
        for index, candidate in enumerate(self._releases):
            if candidate.identifier == release.identifier:
                self.slider.setValue(index)
                return

    def _set_releases(self, releases: List[WaybackRelease]) -> None:
        previous = self.current_release()
        self._releases = list(releases)
        count = len(self._releases)

        self._updating = True
        try:
            self.combo.clear()
            self.combo.addItems([r.long_label for r in self._releases])
            self.slider.setRange(0, max(count - 1, 0))
            index = count - 1
            if previous is not None:
                for i, r in enumerate(self._releases):
                    if r.identifier == previous.identifier:
                        index = i
                        break
            self.slider.setValue(index)
            self.combo.setCurrentIndex(index)
        finally:
            self._updating = False

        if count:
            self.first_label.setText(self._releases[0].label)
            self.last_label.setText(self._releases[-1].label)
            self.status_label.setText(
                f"{count} releases, {self._releases[0].label} to {self._releases[-1].label}"
            )
        self._set_controls_enabled(count > 0)
        self._update_labels()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.slider, self.combo, self.live_check, self.add_fixed_button):
            widget.setEnabled(enabled)

    def _update_labels(self) -> None:
        release = self.current_release()
        if release is None:
            self.date_label.setText("—")
            self.release_label.setText("")
            return
        self.date_label.setText(release.label)
        self.release_label.setText(
            f"Release {self.slider.value() + 1} of {len(self._releases)}  ·  {release.identifier}"
        )
        self.slider.setToolTip(release.long_label)

    # ----------------------------------------------------- catalog signals
    def _on_loading_started(self) -> None:
        self.status_label.setText("Loading Wayback catalog…")
        self.refresh_button.setEnabled(False)

    def _on_loaded(self, releases: list) -> None:
        self.refresh_button.setEnabled(True)
        self._set_releases(releases)

    def _on_failed(self, message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.status_label.setText("Catalog unavailable, press refresh to retry")
        self.status_label.setToolTip(message)

    def _on_visibility_changed(self, visible: bool) -> None:
        if visible and not self.catalog.is_loaded and not self.catalog.is_loading:
            self.catalog.fetch()

    # ------------------------------------------------------ slider / combo
    def _on_slider_changed(self, value: int) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            self.combo.setCurrentIndex(value)
        finally:
            self._updating = False
        self._update_labels()
        if self.live_check.isChecked():
            self._live_timer.start()

    def _on_combo_changed(self, index: int) -> None:
        if self._updating or index < 0:
            return
        # Drives the slider; the slider handler takes care of the rest.
        self.slider.setValue(index)

    # ------------------------------------------------------------ live layer
    def _on_live_toggled(self, checked: bool) -> None:
        if checked:
            self._apply_live()
        else:
            self._live_timer.stop()
            self.layer_manager.remove_live_layer()

    def _flush_live(self) -> None:
        if self._live_timer.isActive():
            self._live_timer.stop()
            self._apply_live()

    def _apply_live(self) -> None:
        if not self.live_check.isChecked():
            return
        release = self.current_release()
        if release is None:
            return
        QgsApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.layer_manager.set_live_release(release)
        except LayerError as exc:
            self._warn(str(exc))
            self._set_live_checked_silently(False)
        finally:
            QgsApplication.restoreOverrideCursor()

    def _set_live_checked_silently(self, checked: bool) -> None:
        self.live_check.blockSignals(True)
        self.live_check.setChecked(checked)
        self.live_check.blockSignals(False)

    def _on_layers_removed(self, *_args) -> None:
        # Live layer removed from the layer tree by the user: reflect it in the UI.
        if self.live_check.isChecked() and self.layer_manager.live_layer() is None:
            self._live_timer.stop()
            self._set_live_checked_silently(False)

    # ------------------------------------------------------------- buttons
    def _on_add_fixed(self) -> None:
        release = self.current_release()
        if release is None:
            return
        QgsApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            layer = self.layer_manager.add_fixed_layer(release)
        except LayerError as exc:
            self._warn(str(exc))
            return
        finally:
            QgsApplication.restoreOverrideCursor()
        self._info(f"Added layer '{layer.name()}' to the {MESSAGE_TITLE} group.",
                   Qgis.MessageLevel.Success)

    # ------------------------------------------------------------ messages
    def _warn(self, message: str) -> None:
        self.iface.messageBar().pushMessage(MESSAGE_TITLE, message, Qgis.MessageLevel.Warning, 8)

    def _info(self, message: str, level=Qgis.MessageLevel.Info) -> None:
        self.iface.messageBar().pushMessage(MESSAGE_TITLE, message, level, 4)
