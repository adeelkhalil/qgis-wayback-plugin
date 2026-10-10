"""Layer-tree management for Wayback layers.

Everything that touches :class:`QgsProject` lives here so the dock widget stays thin.
"""

from __future__ import annotations

from typing import List, Optional

from qgis.PyQt.QtCore import QObject
from qgis.core import (
    QgsDataProvider,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    QgsMapLayer,
    QgsProject,
    QgsRasterLayer,
)

from .catalog import (
    ESRI_ATTRIBUTION,
    ESRI_ATTRIBUTION_URL,
    ESRI_TERMS_URL,
    ESRI_WAYBACK_CREDIT,
    ESRI_WAYBACK_URL,
    WAYBACK_CAPABILITIES_URL,
    WaybackRelease,
    build_wmts_uri,
)

GROUP_NAME = "Esri Wayback"
PROP_IDENTIFIER = "wayback/identifier"
PROP_ROLE = "wayback/role"
ROLE_FIXED = "fixed"
ROLE_LIVE = "live"
LIVE_LAYER_PREFIX = "Wayback live"


class LayerError(Exception):
    """Raised when a Wayback layer cannot be created or updated."""


def _sip_alive(obj) -> bool:
    """True when the underlying C++ object of a wrapped QObject still exists."""
    if obj is None:
        return False
    try:
        from qgis.PyQt import sip  # type: ignore
    except ImportError:  # pragma: no cover - very old builds
        try:
            import sip  # type: ignore
        except ImportError:
            return True
    try:
        return not sip.isdeleted(obj)
    except (TypeError, RuntimeError):
        return False


class WaybackLayerManager(QObject):
    """Creates Wayback WMTS layers and keeps them in the ``Esri Wayback`` group."""

    def __init__(self, capabilities_url: str = WAYBACK_CAPABILITIES_URL,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self.capabilities_url = capabilities_url

    # --------------------------------------------------------------- helpers
    @staticmethod
    def project() -> QgsProject:
        return QgsProject.instance()

    def group(self, create: bool = True) -> Optional[QgsLayerTreeGroup]:
        root = self.project().layerTreeRoot()
        group = root.findGroup(GROUP_NAME)
        if group is None and create:
            group = root.insertGroup(0, GROUP_NAME)
            group.setExpanded(True)
        return group

    def make_layer(self, release: WaybackRelease, name: Optional[str] = None,
                   role: str = ROLE_FIXED) -> QgsRasterLayer:
        """Create (but do not register) a WMTS raster layer for *release*."""
        uri = build_wmts_uri(release, self.capabilities_url)
        layer = QgsRasterLayer(uri, name or release.layer_name, "wms")
        if not layer.isValid():
            raise LayerError(
                f"QGIS could not open Wayback release {release.label} ({release.identifier}): "
                f"{layer.error().summary() or 'the WMTS provider rejected the layer'}"
            )
        self._tag(layer, release, role)
        return layer

    @staticmethod
    def _tag(layer: QgsMapLayer, release: WaybackRelease, role: str) -> None:
        layer.setCustomProperty(PROP_IDENTIFIER, release.identifier)
        layer.setCustomProperty(PROP_ROLE, role)
        WaybackLayerManager.apply_credits(layer, release)

    @staticmethod
    def apply_credits(layer: QgsMapLayer, release: WaybackRelease) -> None:
        """Attach the Esri attribution to the layer (server properties + metadata)."""
        attribution = f"{ESRI_WAYBACK_CREDIT} {release.label}. {ESRI_ATTRIBUTION}"
        abstract = (
            f"Esri World Imagery Wayback release {release.label} ({release.identifier}).\n"
            f"{ESRI_ATTRIBUTION}\n"
            f"Streamed on demand via WMTS from {ESRI_WAYBACK_URL}\n"
            f"Use is subject to the Esri Terms of Use: {ESRI_TERMS_URL}"
        )
        server_props = getattr(layer, "serverProperties", None)
        props = server_props() if callable(server_props) else None
        if props is not None and hasattr(props, "setAttribution"):
            props.setAttribution(attribution)
            props.setAttributionUrl(ESRI_ATTRIBUTION_URL)
            props.setAbstract(abstract)
            props.setTitle(f"{ESRI_WAYBACK_CREDIT} {release.label}")
        else:  # QGIS < 3.38
            layer.setAttribution(attribution)
            layer.setAttributionUrl(ESRI_ATTRIBUTION_URL)
            layer.setAbstract(abstract)

        metadata = layer.metadata()
        metadata.setTitle(f"{ESRI_WAYBACK_CREDIT} {release.label}")
        metadata.setAbstract(abstract)
        metadata.setRights([ESRI_ATTRIBUTION, "Copyright Esri and its data contributors."])
        metadata.setLicenses([f"Esri Terms of Use: {ESRI_TERMS_URL}"])
        metadata.setKeywords({"source": ["Esri", "World Imagery", "Wayback", release.identifier]})
        layer.setMetadata(metadata)

    @staticmethod
    def is_wayback_layer(layer: QgsMapLayer) -> bool:
        return bool(layer is not None and layer.customProperty(PROP_IDENTIFIER))

    @staticmethod
    def release_identifier(layer: QgsMapLayer) -> Optional[str]:
        value = layer.customProperty(PROP_IDENTIFIER)
        return str(value) if value else None

    def wayback_layers(self) -> List[QgsRasterLayer]:
        return [layer for layer in self.project().mapLayers().values()
                if self.is_wayback_layer(layer)]

    def find_fixed_layer(self, release: WaybackRelease) -> Optional[QgsRasterLayer]:
        for layer in self.wayback_layers():
            if (layer.customProperty(PROP_IDENTIFIER) == release.identifier
                    and layer.customProperty(PROP_ROLE) == ROLE_FIXED):
                return layer
        return None

    # ---------------------------------------------------------- fixed layers
    def add_fixed_layer(self, release: WaybackRelease) -> QgsRasterLayer:
        """Add *release* as a permanent layer at the top of the Wayback group."""
        layer = self.make_layer(release, role=ROLE_FIXED)
        self.project().addMapLayer(layer, False)
        self.group().insertLayer(0, layer)
        return layer

    def ensure_fixed_layer(self, release: WaybackRelease, visible: bool = True,
                           to_top: bool = True) -> QgsRasterLayer:
        """Return the fixed layer for *release*, creating it when missing."""
        layer = self.find_fixed_layer(release)
        if layer is None:
            layer = self.add_fixed_layer(release)
        node = self.project().layerTreeRoot().findLayer(layer.id())
        if node is not None:
            if visible:
                node.setItemVisibilityCheckedParentRecursive(True)
            if to_top:
                self._move_to_top(node)
        return layer

    @staticmethod
    def _move_to_top(node: QgsLayerTreeLayer) -> None:
        parent = node.parent()
        if parent is None or parent.children().index(node) == 0:
            return
        clone = node.clone()
        parent.insertChildNode(0, clone)
        parent.removeChildNode(node)

    # ------------------------------------------------------------ live layer
    def live_layer(self) -> Optional[QgsRasterLayer]:
        for layer in self.wayback_layers():
            if layer.customProperty(PROP_ROLE) == ROLE_LIVE:
                return layer
        return None

    def set_live_release(self, release: WaybackRelease) -> QgsRasterLayer:
        """Point the single live-scrub layer at *release*, creating it if needed."""
        layer = self.live_layer()
        name = f"{LIVE_LAYER_PREFIX}: {release.label}"
        if layer is None:
            layer = self.make_layer(release, name=name, role=ROLE_LIVE)
            self.project().addMapLayer(layer, False)
            self.group().insertLayer(0, layer)
            return layer
        if layer.customProperty(PROP_IDENTIFIER) == release.identifier:
            return layer
        self._switch_source(layer, release, name)
        return layer

    def _switch_source(self, layer: QgsRasterLayer, release: WaybackRelease, name: str) -> None:
        uri = build_wmts_uri(release, self.capabilities_url)
        try:
            layer.setDataSource(uri, name, "wms", QgsDataProvider.ProviderOptions())
        except TypeError:
            # Older signature without provider options.
            layer.setDataSource(uri, name, "wms")
        if not layer.isValid():
            raise LayerError(
                f"Could not switch the live layer to release {release.label}: "
                f"{layer.error().summary() or 'the WMTS provider rejected the layer'}"
            )
        layer.setName(name)
        self._tag(layer, release, ROLE_LIVE)
        layer.triggerRepaint()

    def remove_live_layer(self) -> None:
        layer = self.live_layer()
        if layer is not None:
            self.project().removeMapLayer(layer.id())

    def freeze_live_layer(self) -> Optional[QgsRasterLayer]:
        """Turn the live layer into an ordinary fixed layer (keeps it in the project)."""
        layer = self.live_layer()
        if layer is None:
            return None
        layer.setCustomProperty(PROP_ROLE, ROLE_FIXED)
        layer.setName(layer.name().replace(f"{LIVE_LAYER_PREFIX}: ", "Wayback "))
        return layer
