"""Asynchronous download of the Wayback WMTS capabilities document.

The download goes through :class:`QgsNetworkAccessManager` so it honours the
QGIS proxy, SSL and timeout settings and never blocks the main UI thread.
Parsing is delegated to the Qt-free :mod:`catalog` module.
"""

from __future__ import annotations

from typing import List, Optional

from qgis.PyQt.QtCore import QObject, QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.core import Qgis, QgsMessageLog, QgsNetworkAccessManager

from .catalog import (
    WAYBACK_CAPABILITIES_URL,
    CatalogError,
    WaybackRelease,
    build_wmts_uri,
    parse_capabilities,
)

__all__ = [
    "WAYBACK_CAPABILITIES_URL",
    "WaybackCatalogService",
    "WaybackRelease",
    "build_wmts_uri",
]

LOG_TAG = "Wayback Explorer"


def _log(message: str, level=Qgis.MessageLevel.Info) -> None:
    QgsMessageLog.logMessage(message, LOG_TAG, level)


def _configure_request(request: QNetworkRequest) -> None:
    """Enable redirect following and bypass stale HTTP caches.

    ``RedirectPolicyAttribute`` exists in Qt >= 5.9 and Qt 6, so it works for
    both PyQt5 and PyQt6 based QGIS builds.
    """
    try:
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
    except AttributeError:  # very old Qt: fall back silently
        pass
    request.setAttribute(
        QNetworkRequest.Attribute.CacheLoadControlAttribute,
        QNetworkRequest.CacheLoadControl.PreferNetwork,
    )
    request.setRawHeader(b"User-Agent", b"QGIS Wayback Explorer plugin")


class WaybackCatalogService(QObject):
    """Owns the release catalog and refreshes it asynchronously.

    Signals
    -------
    loading_started
        A download has been started.
    loaded(list)
        The catalog was refreshed; the payload is the sorted list of releases.
    failed(str)
        The download or the parsing failed; the payload is a user-facing message.
    """

    loading_started = pyqtSignal()
    loaded = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, capabilities_url: str = WAYBACK_CAPABILITIES_URL,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self.capabilities_url = capabilities_url
        self._releases: List[WaybackRelease] = []
        self._reply: Optional[QNetworkReply] = None
        self._cancelled = False

    # ------------------------------------------------------------------ state
    @property
    def releases(self) -> List[WaybackRelease]:
        return list(self._releases)

    @property
    def is_loaded(self) -> bool:
        return bool(self._releases)

    @property
    def is_loading(self) -> bool:
        return self._reply is not None

    def find(self, identifier: str) -> Optional[WaybackRelease]:
        for release in self._releases:
            if release.identifier == identifier:
                return release
        return None

    # --------------------------------------------------------------- actions
    def fetch(self) -> None:
        """Start an asynchronous download. No-op when one is already running."""
        if self._reply is not None:
            return
        request = QNetworkRequest(QUrl(self.capabilities_url))
        _configure_request(request)
        self._cancelled = False
        reply = QgsNetworkAccessManager.instance().get(request)
        self._reply = reply
        reply.finished.connect(self._on_reply_finished)
        _log(f"Fetching Wayback catalog from {self.capabilities_url}")
        self.loading_started.emit()

    def cancel(self) -> None:
        """Abort an in-flight download without emitting ``failed``."""
        if self._reply is not None:
            self._cancelled = True
            self._reply.abort()

    # --------------------------------------------------------------- internal
    def _on_reply_finished(self) -> None:
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        data = b""
        try:
            if self._cancelled:
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._fail(f"Could not download the Wayback catalog: {reply.errorString()}")
                return
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status is not None and int(status) >= 400:
                self._fail(f"The Wayback service answered with HTTP {int(status)}.")
                return
            data = bytes(reply.readAll())
        finally:
            reply.deleteLater()

        try:
            releases = parse_capabilities(data)
        except CatalogError as exc:
            self._fail(str(exc))
            return
        except Exception as exc:  # defensive: never let a parser bug kill the UI
            self._fail(f"Unexpected error while reading the Wayback catalog: {exc}")
            return

        self._releases = releases
        _log(f"Wayback catalog loaded: {len(releases)} releases "
             f"({releases[0].label} to {releases[-1].label})")
        self.loaded.emit(list(releases))

    def _fail(self, message: str) -> None:
        _log(message, Qgis.MessageLevel.Warning)
        self.failed.emit(message)
