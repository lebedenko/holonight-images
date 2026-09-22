# Design and inventory

Use HolonightImages::Images from find_package(HolonightImages). image.h exposes Limits, DecodeOptions, Inspection, DecodeResult and ExifFacts. No provider dependency on either application. Qt allocation policy stays at application startup.

Extract Viewer exif_metadata.cpp scanners and numeric tag access; retain formatted strings only in consumer adapters. Extract image_document.cpp simple RIFF WebP fallback; do not expand eligibility to extended/animated containers. Viewer image_document and directory_model use discovery/decoding; frame_source and SVG remain local. Files thumbnail_service and preview_service use inspection/decoding with Ignore; cache validation and verified QFile lifetime remain local.

Existing coverage: Viewer generated JPEG/PNG/WebP/TIFF fixtures, EXIF/GPS fixtures, malformed TIFF, alpha, source limits, navigation/prefetch/cache; Files EXIF JPEG/PNG, thumbnail tiers/metadata/revisions, decode limits, descriptor replacement and stale asynchronous results. Reuse these tests and add provider tests including an installed consumer.

Optional damaged metadata remains absent/partial, preserving existing behavior. Bounded decoding limits source dimensions before entering a codec, requests scaled output and validates actual output bytes afterwards. No promise of interrupting a blocking codec or bounding all codec internal allocations; the application process ceiling remains required.
