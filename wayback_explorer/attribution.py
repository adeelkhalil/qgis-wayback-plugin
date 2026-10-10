"""On-map attribution overlay, shown whenever a Wayback layer is in the main canvas.

The Esri Terms of Use require the data attribution to be visible on any map that
displays Esri imagery.  Layer-level attribution metadata is not visible on the
canvas itself, so this small overlay draws the credit in the bottom-right corner
of the map canvas while at least one Wayback layer is being rendered.
"""

from __future__ import annotations

from typing import Optional

from qgis.PyQt.QtCore import QRectF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPen
from qgis.gui import QgsMapCanvas, QgsMapCanvasItem

from .catalog import ESRI_ATTRIBUTION, ESRI_WAYBACK_CREDIT
from .layers import WaybackLayerManager

ATTRIBUTION_TEXT = f"{ESRI_WAYBACK_CREDIT} | {ESRI_ATTRIBUTION}"
MARGIN = 4
PADDING = 4


class AttributionCanvasItem(QgsMapCanvasItem):
    """Semi-transparent credit badge anchored to the bottom-right of the canvas."""

    def __init__(self, canvas: QgsMapCanvas):
        super().__init__(canvas)
        self._canvas = canvas
        self._text = ATTRIBUTION_TEXT
        self._font = QFont()
        self._font.setPointSizeF(max(self._font.pointSizeF() - 1.5, 7.0))
        self.setZValue(1000)

    def set_text(self, text: str) -> None:
        self._text = text
        self.prepareGeometryChange()
        self.update()

    def _badge_rect(self) -> QRectF:
        metrics = QFontMetricsF(self._font)
        text_rect = metrics.boundingRect(self._text)
        width = min(text_rect.width() + 2 * PADDING, max(self._canvas.width() - 2 * MARGIN, 10))
        height = text_rect.height() + 2 * PADDING
        return QRectF(self._canvas.width() - MARGIN - width,
                      self._canvas.height() - MARGIN - height, width, height)

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        return QRectF(0, 0, self._canvas.width(), self._canvas.height())

    def updatePosition(self) -> None:  # noqa: N802 - Qt override
        self.prepareGeometryChange()
        self.update()

    def paint(self, painter: QPainter, option=None, widget=None) -> None:
        rect = self._badge_rect()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 170)))
        painter.drawRoundedRect(rect, 3, 3)
        painter.setFont(self._font)
        painter.setPen(QPen(QColor(40, 40, 40)))
        text_rect = rect.adjusted(PADDING, 0, -PADDING, 0)
        elided = QFontMetricsF(self._font).elidedText(self._text, Qt.TextElideMode.ElideRight,
                                                      text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, elided)
        painter.restore()


class AttributionOverlay:
    """Shows / hides the attribution badge depending on the canvas layer set."""

    def __init__(self, canvas: QgsMapCanvas):
        self._canvas = canvas
        self._item: Optional[AttributionCanvasItem] = None
        canvas.layersChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        wanted = any(WaybackLayerManager.is_wayback_layer(layer) for layer in self._canvas.layers())
        if wanted and self._item is None:
            self._item = AttributionCanvasItem(self._canvas)
            self._item.update()
        elif not wanted and self._item is not None:
            self._remove_item()
        self._canvas.scene().update()

    def _remove_item(self) -> None:
        if self._item is None:
            return
        scene = self._canvas.scene()
        if scene is not None:
            scene.removeItem(self._item)
        self._item = None

    @property
    def visible(self) -> bool:
        return self._item is not None

    def shutdown(self) -> None:
        try:
            self._canvas.layersChanged.disconnect(self.refresh)
        except (TypeError, RuntimeError):
            pass
        self._remove_item()
