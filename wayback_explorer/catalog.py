"""Pure-Python data model and parser for the Esri Wayback WMTS capabilities document.

This module intentionally has no QGIS or Qt dependency so the parsing logic can be
unit-tested with a plain Python interpreter.  Network access lives in
:mod:`wmts_loader`.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from typing import Iterable, List, Optional

#: Official, public Wayback WMTS capabilities endpoint.
WAYBACK_CAPABILITIES_URL = (
    "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
    "World_Imagery/WMTS/1.0.0/WMTSCapabilities.xml"
)

#: Attribution required by the Esri Terms of Use for World Imagery / Wayback.
#: This is the ``copyrightText`` published by the World Imagery service (October 2026).
ESRI_ATTRIBUTION = "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community"
ESRI_WAYBACK_CREDIT = "Esri World Imagery (Wayback)"
ESRI_WAYBACK_URL = "https://livingatlas.arcgis.com/wayback/"
ESRI_TERMS_URL = "https://www.esri.com/en-us/legal/terms/full-master-agreement"
ESRI_ATTRIBUTION_URL = "https://www.esri.com/en-us/legal/terms/data-attributions"

#: Tile matrix sets we know render correctly in EPSG:3857, in order of preference.
PREFERRED_TILE_MATRIX_SETS = ("GoogleMapsCompatible", "default028mm")

#: Image formats in order of preference when a layer advertises several.
PREFERRED_FORMATS = ("image/jpeg", "image/jpgpng", "image/png")

_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_IDENTIFIER_RE = re.compile(r"(\d{4})_R(\d+)", re.IGNORECASE)


class CatalogError(Exception):
    """Raised when the capabilities document cannot be turned into a catalog."""


@dataclass(frozen=True)
class WaybackRelease:
    """One historical World Imagery release exposed as a WMTS layer."""

    identifier: str
    title: str
    release_date: Optional[date]
    image_format: str
    style: str
    tile_matrix_set: str
    release_number: Optional[int]

    @property
    def label(self) -> str:
        """Human readable date (``YYYY-MM-DD``), falling back to the WMTS title."""
        if self.release_date is not None:
            return self.release_date.isoformat()
        return self.title

    @property
    def long_label(self) -> str:
        return f"{self.label}  ({self.identifier})"

    @property
    def layer_name(self) -> str:
        return f"Wayback {self.label}"

    @property
    def sort_key(self):
        """Chronological key: release date first, then identifier year / number."""
        year, number = None, None
        match = _IDENTIFIER_RE.search(self.identifier)
        if match:
            year, number = int(match.group(1)), int(match.group(2))
        d = self.release_date or (date(year, 1, 1) if year else date.min)
        return (d, year or 0, number or 0, self.identifier)


def _local(tag: str) -> str:
    """Strip an XML namespace from a tag name."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _children(element: ET.Element, name: str) -> List[ET.Element]:
    return [child for child in element if _local(child.tag) == name]


def _first_text(element: ET.Element, name: str) -> Optional[str]:
    for child in _children(element, name):
        if child.text and child.text.strip():
            return child.text.strip()
    return None


def _pick(candidates: Iterable[str], preferred: Iterable[str], default: str) -> str:
    candidates = [c for c in candidates if c]
    for wanted in preferred:
        if wanted in candidates:
            return wanted
    return candidates[0] if candidates else default


def _parse_date(title: str, identifier: str) -> Optional[date]:
    for source in (title, identifier):
        match = _DATE_RE.search(source or "")
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                continue
    return None


def _parse_release_number(identifier: str) -> Optional[int]:
    match = _IDENTIFIER_RE.search(identifier or "")
    return int(match.group(2)) if match else None


def parse_layer(layer: ET.Element) -> Optional[WaybackRelease]:
    """Convert a ``<Layer>`` element into a release, or ``None`` if it is unusable."""
    identifier = _first_text(layer, "Identifier")
    if not identifier:
        return None
    title = _first_text(layer, "Title") or identifier

    formats = [f.text.strip() for f in _children(layer, "Format") if f.text]
    image_format = _pick(formats, PREFERRED_FORMATS, "image/jpeg")

    style = "default"
    styles = _children(layer, "Style")
    default_styles = [s for s in styles if (s.get("isDefault") or "").lower() == "true"]
    for candidate in default_styles + styles:
        style_id = _first_text(candidate, "Identifier")
        if style_id:
            style = style_id
            break

    tile_matrix_sets = []
    for link in _children(layer, "TileMatrixSetLink"):
        tms = _first_text(link, "TileMatrixSet")
        if tms:
            tile_matrix_sets.append(tms)
    tile_matrix_set = _pick(tile_matrix_sets, PREFERRED_TILE_MATRIX_SETS, "")

    return WaybackRelease(
        identifier=identifier,
        title=title,
        release_date=_parse_date(title, identifier),
        image_format=image_format,
        style=style,
        tile_matrix_set=tile_matrix_set,
        release_number=_parse_release_number(identifier),
    )


def parse_capabilities(xml_data: bytes) -> List[WaybackRelease]:
    """Parse a WMTS capabilities document into a chronologically sorted release list.

    The parser is namespace agnostic because the Wayback service has switched
    between ``http://`` and ``https://`` OGC namespace URIs over time.
    """
    if not xml_data:
        raise CatalogError("The Wayback service returned an empty response.")
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as exc:
        raise CatalogError(f"Malformed WMTS capabilities XML: {exc}") from exc

    if _local(root.tag) != "Capabilities":
        raise CatalogError(
            f"Unexpected root element <{_local(root.tag)}>; expected a WMTS <Capabilities> document."
        )

    contents = next(iter(_children(root, "Contents")), None)
    if contents is None:
        raise CatalogError("The capabilities document has no <Contents> section.")

    releases = []
    seen = set()
    for layer in _children(contents, "Layer"):
        release = parse_layer(layer)
        if release is None or release.identifier in seen:
            continue
        seen.add(release.identifier)
        releases.append(release)

    if not releases:
        raise CatalogError("No Wayback imagery layers were found in the capabilities document.")

    releases.sort(key=lambda r: r.sort_key)
    return releases


def build_wmts_uri(release: WaybackRelease, capabilities_url: str = WAYBACK_CAPABILITIES_URL) -> str:
    """Build the QGIS ``wms`` provider URI that streams one release via WMTS.

    The identifier, style, format and tile matrix set are taken from the
    capabilities document itself so the URI always matches what the service
    advertises.
    """
    params = [
        ("crs", "EPSG:3857"),
        ("dpiMode", "7"),
        ("format", release.image_format),
        ("layers", release.identifier),
        ("styles", release.style or "default"),
    ]
    if release.tile_matrix_set:
        params.append(("tileMatrixSet", release.tile_matrix_set))
    params.append(("url", capabilities_url))
    return "&".join(f"{key}={value}" for key, value in params)
