# Wayback Explorer (QGIS plugin)

Browse the [Esri World Imagery Wayback](https://livingatlas.arcgis.com/wayback/) archive inside QGIS:

- A **timeline slider** and a **release dropdown** across every published release (2014 to today).
- **Add Layer** adds the selected release to the project as a streamed WMTS layer.
- An optional **live scrub layer** that updates in place as you move the slider.

All imagery is streamed on demand through the native QGIS WMTS provider from the official
capabilities endpoint. The plugin never bulk-downloads tiles and never caches imagery to disk,
in line with the Esri Terms of Use. All loaded layers are grouped under **Esri Wayback** in the
layer tree.

## Credits and terms of use

Imagery: **Esri World Imagery (Wayback)**. Source: Esri, Vantor, Earthstar Geographics, and the
GIS User Community. Wayback is part of the [Esri Living Atlas](https://livingatlas.arcgis.com/wayback/)
and its use is governed by the
[Esri Terms of Use](https://www.esri.com/en-us/legal/terms/full-master-agreement) and the
[Esri data attribution requirements](https://www.esri.com/en-us/legal/terms/data-attributions).

The plugin honours these terms by:

- streaming tiles on demand only (no bulk download, no export, no disk cache);
- writing the attribution into every layer's server properties and metadata
  (*Layer Properties > QGIS Server / Metadata*);
- drawing an attribution badge in the bottom-right corner of the map canvas whenever a Wayback
  layer is displayed;
- showing the credit and links in the timeline dock.

This plugin is an independent open-source project and is not affiliated with or endorsed by Esri.

## Requirements

- QGIS 3.22 or newer (also works with the QGIS 4.0 / Qt 6 build).
- No third-party Python packages.

## Installation

Copy (or symlink) the `wayback_explorer` folder into your QGIS profile plugin directory and
enable *Wayback Explorer* in *Plugins > Manage and Install Plugins*.

| Platform | Plugin directory |
| --- | --- |
| Windows | `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\` |
| Linux | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/` |
| macOS | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/` |

## Usage

1. Open the **Wayback Timeline** dock (toolbar or *Web > Wayback Explorer*). The catalog is
   fetched asynchronously on first show.
2. Scrub the slider or pick a release in the dropdown.
3. Press **Add Layer** to add the release to the project, or tick **Live scrub layer** to keep one
   layer that follows the slider.

## Why some releases rendered blank (and the built-in fix)

Most Wayback releases do not store every tile themselves. The service answers a tile request
with an HTTP 301 to the release that actually holds that tile, using a relative `Location`
header. With the QGIS network disk cache active (the default), QGIS fails to follow that
redirect and draws nothing, so only releases that own their tiles outright (typically the
oldest and the newest) appear to work.

The plugin installs a network request preprocessor (QGIS 3.22+) for `*.maptiles.arcgis.com`
that bypasses the disk cache and lets Qt resolve the redirect. This also guarantees that no
imagery is cached to disk. The preprocessor is removed when the plugin is unloaded.

## Module overview

| File | Responsibility |
| --- | --- |
| `catalog.py` | Qt-free release model, WMTS capabilities parser, QGIS URI builder |
| `wmts_loader.py` | Asynchronous download via `QgsNetworkAccessManager` |
| `layers.py` | Layer-tree group management, fixed and live layers |
| `network.py` | Request preprocessor that makes redirected Wayback tiles load |
| `attribution.py` | On-canvas Esri attribution badge |
| `dock_widget.py` | Timeline dock widget |
| `plugin.py` | QGIS lifecycle: toolbar, menu, dock, unload |

Run the parser tests with a plain Python interpreter:

```
python wayback_explorer/tests/test_catalog.py
```
