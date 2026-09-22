# Design

Keep all changes in the existing test executable and EXIF fixture header. A caller-owned,
unbuffered QBuffer subclass counts reads/seeks and bytes, injects persistent failures from
a selected operation onward, and sets cancellation after a selected read. Successful runs
discover I/O boundaries; regressions do not freeze Qt codec call counts.

Inspection without metadata, raster decoding and standalone metadata extraction each
exercise initial/later read and seek failures and pre-work/read-triggered cancellation.
Decode failures require a null image, metadata failures require empty facts, and callers
retain open devices. PNG/WebP extraction and multi-block TIFF scanning exercise the same
faults and cancellation separately.

Extend the TIFF/JPEG builders with reusable JPEG segments, PNG chunks and padded WebP
chunks. PNG CRC placeholders are exclusively for metadata extraction; raster independence
uses a real encoded JPEG. Test exact resource boundaries and one-step rejection, and
place EXIF precisely at/beyond record budgets. Byte counters establish bounded scans.
Truncated containers, padding loss, invalid offsets, cyclic IFD links, wrong field types,
zero denominators and invalid GPS values must retain best-effort behavior.

No regression demonstrated a production contract violation. Provider implementation,
public API, codecs, orientation, scheduling and consumer artifacts remain unchanged.
