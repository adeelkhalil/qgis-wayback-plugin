"""Workaround for Wayback tile redirects in the QGIS network stack.

Most Wayback releases do not store every tile themselves: the service answers a
tile request with an HTTP 301 to the release that actually holds that tile, using
a *relative* ``Location`` header.  When the QGIS network disk cache is active
(it is, by default) the automatic redirect fails with ``HostNotFoundError`` and
the WMTS provider draws nothing, so only releases that own their tiles outright
(typically the oldest and the newest) appear to work.

The fix installs a request preprocessor that, for Wayback hosts only:

* bypasses the HTTP disk cache (``AlwaysNetwork`` and no cache save), which is
  also what the Esri Terms of Use ask for (no imagery cached to disk), and
* forces Qt's own ``NoLessSafeRedirectPolicy`` so the redirect is resolved by Qt
  rather than by the WMTS tile handler, which cannot resolve relative targets.

QGIS keeps its in-memory tile cache, so panning back and forth stays cheap.
"""

from __future__ import annotations

from typing import Optional

from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsNetworkAccessManager

WAYBACK_HOST_SUFFIX = "maptiles.arcgis.com"


def _preprocess(request: QNetworkRequest) -> None:
    host = request.url().host().lower()
    if not host.endswith(WAYBACK_HOST_SUFFIX):
        return
    attr = QNetworkRequest.Attribute
    request.setAttribute(attr.CacheLoadControlAttribute, QNetworkRequest.CacheLoadControl.AlwaysNetwork)
    request.setAttribute(attr.CacheSaveControlAttribute, False)
    try:
        request.setAttribute(attr.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
    except AttributeError:  # Qt < 5.9
        pass


class WaybackNetworkFix:
    """Installs / removes the request preprocessor (QGIS >= 3.22)."""

    def __init__(self) -> None:
        self._id: Optional[str] = None

    @property
    def active(self) -> bool:
        return self._id is not None

    def install(self) -> bool:
        if self._id is not None:
            return True
        setter = getattr(QgsNetworkAccessManager, "setRequestPreprocessor", None)
        if setter is None:
            return False
        self._id = setter(_preprocess)
        return True

    def remove(self) -> None:
        if self._id is None:
            return
        remover = getattr(QgsNetworkAccessManager, "removeRequestPreprocessor", None)
        if remover is not None:
            try:
                remover(self._id)
            except Exception:  # pragma: no cover - never block unload
                pass
        self._id = None
