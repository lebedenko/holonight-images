#!/usr/bin/env python3
"""Independent release fixtures: stdlib PNG/BMP/TIFF, fixed JPEG, libwebp RGBA."""
import base64
import ctypes
import ctypes.util
from pathlib import Path
import struct
import sys
import zlib

# TIFF field types: name -> (type code, struct format of one value).
TIFF_KINDS = {'BYTE': (1, 'B'), 'ASCII': (2, None), 'SHORT': (3, 'H'), 'LONG': (4, 'I'), 'RATIONAL': (5, 'II')}


def tiff_header(e, first_ifd=8):
    return (b'II*\0' if e == '<' else b'MM\0*') + struct.pack(e + 'I', first_ifd)


def tiff_ifd(e, base, entries, next_ifd=0):
    """One IFD placed at file offset base, followed by the values that do not fit its 4-byte value words.

    entries: (tag, kind, values); ASCII values are bytes, RATIONAL values are (numerator, denominator) pairs.
    Entries are written in tag order. The length depends only on the kinds and counts, never on the values.
    """
    entries = sorted(entries, key=lambda entry: entry[0])
    table_length = 2 + 12 * len(entries) + 4
    table = struct.pack(e + 'H', len(entries))
    extra = b''
    for tag, kind, values in entries:
        code, unit = TIFF_KINDS[kind]
        if kind == 'ASCII':
            raw = values
        elif kind == 'RATIONAL':
            raw = b''.join(struct.pack(e + unit, *pair) for pair in values)
        else:
            raw = b''.join(struct.pack(e + unit, value) for value in values)
        count = len(values)
        if len(raw) <= 4:
            value = raw.ljust(4, b'\0')  # Inline values are left-justified in file order.
        else:
            value = struct.pack(e + 'I', base + table_length + len(extra))
            extra += raw + bytes(len(raw) % 2)
        table += struct.pack(e + 'HHI', tag, code, count) + value
    return table + struct.pack(e + 'I', next_ifd) + extra


def tiff_image_tags(strip_offset, pixels, photometric, bits, extra=(), compression=1, width=1, height=1):
    samples = len(bits)
    return [(256, 'LONG', [width]), (257, 'LONG', [height]), (258, 'SHORT', bits), (259, 'SHORT', [compression]),
            (262, 'SHORT', [photometric]), (273, 'LONG', [strip_offset]), (277, 'SHORT', [samples]),
            (278, 'LONG', [height]), (279, 'LONG', [len(pixels)])] + list(extra)


def tiff_page(e, base, pixels, photometric, bits, extra=(), next_ifd=0, compression=1):
    """IFD, its out-of-line values and one strip, starting at file offset base."""
    length = len(tiff_ifd(e, base, tiff_image_tags(0, pixels, photometric, bits, extra, compression)))
    tags = tiff_image_tags(base + length, pixels, photometric, bits, extra, compression)
    return tiff_ifd(e, base, tags, next_ifd) + pixels


def tiff_file(pixels, photometric, bits, extra=(), e='<', compression=1):
    return tiff_header(e) + tiff_page(e, 8, pixels, photometric, bits, extra, compression=compression)


def tiff_two_pages(e='<'):
    red = tiff_page(e, 8, b'\xff\0\0', 2, [8, 8, 8])
    second = 8 + len(red)
    return (tiff_header(e) + tiff_page(e, 8, b'\xff\0\0', 2, [8, 8, 8], next_ifd=second)
            + tiff_page(e, second, b'\0\xff\0', 2, [8, 8, 8]))


def tiff_with_exif(e):
    """RGB8 1x1 with the strip first and IFD0 after it, as libtiff-style writers lay files out."""
    pixels = b'\xff\0\0'
    pixel_offset = 8
    ifd0_offset = pixel_offset + len(pixels) + 1
    camera = [(271, 'ASCII', b'Acme\0'), (272, 'ASCII', b'TiffCam\0')]
    tags = tiff_image_tags(pixel_offset, pixels, 2, [8, 8, 8], camera + [(34665, 'LONG', [0]), (34853, 'LONG', [0])])
    ifd0_length = len(tiff_ifd(e, ifd0_offset, tags))
    exif_offset = ifd0_offset + ifd0_length
    exif_ifd = tiff_ifd(e, exif_offset, [(34855, 'SHORT', [400])])
    gps_offset = exif_offset + len(exif_ifd)
    gps_ifd = tiff_ifd(e, gps_offset, [(1, 'ASCII', b'N\0'), (2, 'RATIONAL', [(50, 1), (30, 1), (0, 1)]),
                                       (3, 'ASCII', b'E\0'), (4, 'RATIONAL', [(30, 1), (15, 1), (0, 1)])])
    pointers = [(34665, 'LONG', [exif_offset]), (34853, 'LONG', [gps_offset])]
    tags = tiff_image_tags(pixel_offset, pixels, 2, [8, 8, 8], camera + pointers)
    return tiff_header(e, ifd0_offset) + pixels + b'\0' + tiff_ifd(e, ifd0_offset, tags) + exif_ifd + gps_ifd


def tiff_lzw_single_pixel(data):
    """TIFF LZW (MSB-first, 9-bit codes): clear code, each byte as a literal, end code. Short enough that the width never grows."""
    bits = ''.join(format(code, '09b') for code in [256, *data, 257])
    bits += '0' * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, 'big')


def tiff_tiled():
    """One 16x16 RGB tile holding a 1x1 image: the tile tags replace the strip tags."""
    tile = b'\xff\0\0' * 256

    def tags(offset):
        return [(256, 'LONG', [1]), (257, 'LONG', [1]), (258, 'SHORT', [8, 8, 8]), (259, 'SHORT', [1]),
                (262, 'SHORT', [2]), (277, 'SHORT', [3]), (322, 'LONG', [16]), (323, 'LONG', [16]),
                (324, 'LONG', [offset]), (325, 'LONG', [len(tile)])]
    return tiff_header('<') + tiff_ifd('<', 8, tags(8 + len(tiff_ifd('<', 8, tags(0))))) + tile


def tiff_bigtiff():
    """BigTIFF (magic 43): 8-byte offsets, 20-byte IFD entries. Uncompressed RGB8 1x1, strip after the IFD."""
    def entry(tag, code, value):
        return struct.pack('<HHQ', tag, code, 1) + value.ljust(8, b'\0')

    def ifd(strip_offset):
        entries = [entry(256, 4, struct.pack('<I', 1)), entry(257, 4, struct.pack('<I', 1)),
                   struct.pack('<HHQ', 258, 3, 3) + struct.pack('<HHH', 8, 8, 8).ljust(8, b'\0'),
                   entry(259, 3, struct.pack('<H', 1)), entry(262, 3, struct.pack('<H', 2)),
                   entry(273, 4, struct.pack('<I', strip_offset)), entry(277, 3, struct.pack('<H', 3)),
                   entry(278, 4, struct.pack('<I', 1)), entry(279, 4, struct.pack('<I', 3))]
        return struct.pack('<Q', len(entries)) + b''.join(entries) + struct.pack('<Q', 0)
    return b'II+\0' + struct.pack('<HHQ', 8, 0, 16) + ifd(16 + len(ifd(0))) + b'\xff\0\0'


def build_tiff_fixtures():
    """Every TIFF fixture by file name; a pure function of this script, so two calls return identical bytes."""
    rgb8 = tiff_file(b'\xff\0\0', 2, [8, 8, 8])
    # Palette entry 2 is red; the ColorMap holds all reds, then all greens, then all blues.
    color_map = [0] * 768
    color_map[2] = 0xffff
    return {
        'tiff-rgb8.tif': rgb8,
        # Alpha 128 is unassociated (ExtraSamples 2), so the stored bytes are not premultiplied.
        'sample.tif': tiff_file(b'\xff\0\0\x80', 2, [8, 8, 8, 8], [(338, 'SHORT', [2])]),
        'tiff-gray8.tif': tiff_file(b'\x80', 1, [8]),
        'tiff-palette8.tif': tiff_file(b'\x02', 3, [8], [(320, 'SHORT', color_map)]),
        'tiff-two-page.tif': tiff_two_pages(),
        # Two bytes short of the strip: the IFD is intact, so the size is known but the pixels are not.
        'tiff-truncated.tif': rgb8[:-2],
        'tiff-exif.tif': tiff_with_exif('<'),
        'tiff-exif-be.tif': tiff_with_exif('>'),
        # Best-effort variants. They may decode or fail, but must never crash or hang.
        'tiff-be-rgb16.tif': tiff_file(struct.pack('<3H', 0xffff, 0, 0), 2, [16, 16, 16]),
        'tiff-be-float.tif': tiff_file(struct.pack('<3f', 1, 0, 0), 2, [32, 32, 32], [(339, 'SHORT', [3, 3, 3])]),
        'tiff-be-cmyk.tif': tiff_file(b'\0\xff\xff\0', 5, [8, 8, 8, 8]),
        'tiff-be-lab.tif': tiff_file(b'\x80\x80\x80', 8, [8, 8, 8]),
        'tiff-be-tiled.tif': tiff_tiled(),
        'tiff-be-bigtiff.tif': tiff_bigtiff(),
        'tiff-be-lzw.tif': tiff_file(tiff_lzw_single_pixel(b'\xff\0\0'), 2, [8, 8, 8], compression=5),
        'tiff-be-packbits.tif': tiff_file(b'\x02\xff\0\0', 2, [8, 8, 8], compression=32773),
        'tiff-be-deflate.tif': tiff_file(zlib.compress(b'\xff\0\0'), 2, [8, 8, 8], compression=8),
    }


def self_check():
    """Prove the TIFF fixtures are deterministic and made without Qt or a TIFF library."""
    if build_tiff_fixtures() != build_tiff_fixtures():
        return 'TIFF fixtures differ between two builds'
    forbidden = [name for name in sys.modules
                 if name.split('.')[0] in ('PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'PIL', 'tifffile', 'libtiff')]
    if forbidden:
        return 'TIFF fixtures must not use ' + ', '.join(sorted(forbidden))
    return None


if __name__ == '__main__' and sys.argv[1:] == ['--self-check']:
    # Runs before the libwebp block below, which needs a system library the check does not.
    sys.exit(self_check())

TIFF_FIXTURES = build_tiff_fixtures()


def chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))


png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
       + chunk(b'IDAT', zlib.compress(b'\0\xff\0\0\x80')) + chunk(b'IEND', b''))
jpeg = base64.b64decode('/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAUACgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDi6KKK+ZP3E6Xwl/y+f8A/9mrpa8tuta1DSNn2G48rzc7/AJFbOOnUH1NVv+E08Qf9BD/yDH/8TXs4TgTMc1orG0JwUZbXcr6O3SLW67n88cc5PXxGf4irBqz5d7/yRXY9boryT/hNPEH/AEEP/IMf/wATRXT/AMQwzf8A5+U/vl/8gfJ/6v4n+aP3v/I0aKKK+dP6zMfXP+WH/Av6VkUUV+48H/8AIlo/9vf+lyPxzir/AJG9b/t3/wBJiFFFFfTHzx//2Q==')
# BMP: one opaque red pixel, bottom-up BGR row padded to four bytes.
bmp = (b'BM' + struct.pack('<IHHI', 58, 0, 0, 54)
       + struct.pack('<IiiHHIIiiII', 40, 1, 1, 1, 24, 0, 4, 0, 0, 0, 0)
       + b'\0\0\xff\0')
# WebP lossless fixture encoded by libwebp, independently of Qt's image handlers.
codec = ctypes.CDLL(ctypes.util.find_library('webp'))
codec.WebPEncodeLosslessRGBA.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
codec.WebPEncodeLosslessRGBA.restype = ctypes.c_size_t
codec.WebPFree.argtypes = [ctypes.c_void_p]
output = ctypes.c_void_p()
size = codec.WebPEncodeLosslessRGBA(b'\xff\0\0\x80', 1, 1, 4, ctypes.byref(output))
if not size:
    raise RuntimeError('Cannot encode independent WebP fixture')
webp = ctypes.string_at(output, size)
codec.WebPFree(output)
# Preserve the exact compact regression even if a future encoder changes output.
compact_webp = bytes.fromhex('524946461c000000574542505650384c0f0000002f000000100710fd8f020622a2ff0100')
# Also exercise a normal RIFF with an optional unknown chunk. Qt 6.11.2 cannot
# scan the compact 36-byte stream; keep it separately as the mandatory compact regression.
webp += b'JUNK' + struct.pack('<I', 32) + bytes(32)
webp = webp[:4] + struct.pack('<I', len(webp) - 8) + webp[8:]
# EXIF orientation 6: stored 40x20 JPEG must display as 20x40.
exif = bytes.fromhex('ffe1002245786966000049492a0008000000010012010300010000000600000000000000')
jpeg = jpeg[:2] + exif + jpeg[2:]

def riff_chunk(kind, payload):
    return kind + struct.pack('<I', len(payload)) + payload + bytes(len(payload) % 2)


def riff(payload):
    return b'RIFF' + struct.pack('<I', len(payload) + 4) + b'WEBP' + payload


extended_webp = riff(riff_chunk(b'VP8X', b'\x10' + bytes(9)) + compact_webp[12:])
# Two independently specified animation frames, both red at alpha 128.
frame = riff_chunk(b'ANMF', bytes(12) + b'\x64\0\0\x02' + compact_webp[12:])
animated_webp = riff(riff_chunk(b'VP8X', b'\x12' + bytes(9))
                     + riff_chunk(b'ANIM', bytes(6)) + frame + frame)
codec.WebPEncodeRGBA.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_float, ctypes.POINTER(ctypes.c_void_p)]
codec.WebPEncodeRGBA.restype = ctypes.c_size_t
size = codec.WebPEncodeRGBA(b'\xff\0\0\xff', 1, 1, 4, 90, ctypes.byref(output))
if not size:
    raise RuntimeError('Cannot encode independent lossy WebP fixture')
lossy_webp = ctypes.string_at(output, size)
codec.WebPFree(output)



def gif_fixture(version, frames, loop=None):
    """Two-colour (red, green) 1x1 GIF. frames: (delay_cs, disposal, transparent_index or None, pixel_index).

    GIF87a has no extension blocks, so frames carry no delay, disposal or transparency there.
    """
    data = version + struct.pack('<HHBBB', 1, 1, 0x80, 0, 0) + bytes.fromhex('ff000000ff00')
    if loop is not None:
        data += b'\x21\xff\x0bNETSCAPE2.0\x03\x01' + struct.pack('<H', loop) + b'\0'
    for delay, disposal, transparent, pixel in frames:
        if version == b'GIF89a':
            flags = (disposal << 2) | (1 if transparent is not None else 0)
            data += b'\x21\xf9\x04' + struct.pack('<BHB', flags, delay, transparent or 0) + b'\0'
        data += b'\x2c' + struct.pack('<HHHHB', 0, 0, 1, 1, 0) + b'\x02\x02' + (b'\x44' if pixel == 0 else b'\x4c') + b'\x01\0'
    return data + b'\x3b'


# Delays are 100 ms and 200 ms; the animation repeats forever (sample) or twice (transparent).
GIF_FIXTURES = {
    'sample.gif': gif_fixture(b'GIF89a', [(10, 1, None, 0), (20, 1, None, 1)], loop=0),
    'gif87a.gif': gif_fixture(b'GIF87a', [(0, 0, None, 0), (0, 0, None, 1)]),
    'transparent.gif': gif_fixture(b'GIF89a', [(10, 2, None, 0), (20, 2, 1, 1)], loop=2),
}

FORMATS = {'png': png, 'jpg': jpeg, 'bmp': bmp, 'webp': webp}

if __name__ == '__main__':
    destination = Path(sys.argv[1])
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'compact.webp').write_bytes(compact_webp)
    (destination / 'extended.webp').write_bytes(extended_webp)
    (destination / 'animated.webp').write_bytes(animated_webp)
    (destination / 'lossy.webp').write_bytes(lossy_webp)
    for name, data in GIF_FIXTURES.items():
        (destination / name).write_bytes(data)
    for name, data in TIFF_FIXTURES.items():
        (destination / name).write_bytes(data)
    for extension, data in FORMATS.items():
        (destination / ('sample.' + extension)).write_bytes(data)
