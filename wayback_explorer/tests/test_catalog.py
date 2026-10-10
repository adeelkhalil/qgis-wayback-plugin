"""Unit tests for the Qt-free catalog parser.  Run with ``python -m unittest``."""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from wayback_explorer.catalog import (  # noqa: E402
    CatalogError,
    build_wmts_uri,
    parse_capabilities,
)

SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<Capabilities xmlns="https://www.opengis.net/wmts/1.0" xmlns:ows="https://www.opengis.net/ows/1.1" version="1.0.0">
  <Contents>
    <Layer>
      <ows:Title>World Imagery (Wayback 2024-05-02)</ows:Title>
      <ows:Identifier>WB_2024_R06</ows:Identifier>
      <Style isDefault="true"><ows:Identifier>default</ows:Identifier></Style>
      <Format>image/jpeg</Format>
      <TileMatrixSetLink><TileMatrixSet>default028mm</TileMatrixSet></TileMatrixSetLink>
      <TileMatrixSetLink><TileMatrixSet>GoogleMapsCompatible</TileMatrixSet></TileMatrixSetLink>
    </Layer>
    <Layer>
      <ows:Title>World Imagery (Wayback 2014-02-20)</ows:Title>
      <ows:Identifier>WB_2014_R01</ows:Identifier>
      <Style isDefault="true"><ows:Identifier>default</ows:Identifier></Style>
      <Format>image/jpeg</Format>
      <TileMatrixSetLink><TileMatrixSet>default028mm</TileMatrixSet></TileMatrixSetLink>
    </Layer>
    <Layer>
      <ows:Title>Undated release</ows:Title>
      <ows:Identifier>WB_2019_R03</ows:Identifier>
      <Format>image/png</Format>
    </Layer>
  </Contents>
</Capabilities>
"""


class ParseCapabilitiesTests(unittest.TestCase):
    def test_parses_and_sorts_chronologically(self):
        releases = parse_capabilities(SAMPLE)
        self.assertEqual([r.identifier for r in releases],
                         ["WB_2014_R01", "WB_2019_R03", "WB_2024_R06"])
        self.assertEqual(releases[0].release_date, date(2014, 2, 20))
        self.assertEqual(releases[-1].release_number, 6)

    def test_prefers_google_maps_compatible_tile_matrix_set(self):
        releases = {r.identifier: r for r in parse_capabilities(SAMPLE)}
        self.assertEqual(releases["WB_2024_R06"].tile_matrix_set, "GoogleMapsCompatible")
        self.assertEqual(releases["WB_2014_R01"].tile_matrix_set, "default028mm")

    def test_undated_layer_falls_back_to_title_and_identifier_year(self):
        releases = {r.identifier: r for r in parse_capabilities(SAMPLE)}
        undated = releases["WB_2019_R03"]
        self.assertIsNone(undated.release_date)
        self.assertEqual(undated.label, "Undated release")
        self.assertEqual(undated.image_format, "image/png")
        self.assertEqual(undated.style, "default")

    def test_http_namespace_is_accepted_too(self):
        data = SAMPLE.replace(b"https://www.opengis.net", b"http://www.opengis.net")
        self.assertEqual(len(parse_capabilities(data)), 3)

    def test_malformed_xml_raises_catalog_error(self):
        with self.assertRaises(CatalogError):
            parse_capabilities(b"<Capabilities><Contents>")

    def test_empty_and_wrong_documents_raise(self):
        with self.assertRaises(CatalogError):
            parse_capabilities(b"")
        with self.assertRaises(CatalogError):
            parse_capabilities(b"<html><body>Service unavailable</body></html>")
        with self.assertRaises(CatalogError):
            parse_capabilities(b"<Capabilities><Contents/></Capabilities>")

    def test_uri_uses_values_from_capabilities(self):
        release = parse_capabilities(SAMPLE)[-1]
        uri = build_wmts_uri(release, "https://example.test/WMTSCapabilities.xml")
        self.assertEqual(
            uri,
            "crs=EPSG:3857&dpiMode=7&format=image/jpeg&layers=WB_2024_R06&styles=default"
            "&tileMatrixSet=GoogleMapsCompatible&url=https://example.test/WMTSCapabilities.xml",
        )


if __name__ == "__main__":
    unittest.main()
