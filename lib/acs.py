"""Decode Microsoft Agent character (.acs) files far enough to get a thumbnail.

Implements the MSAgent Character Data Specification: an ACS file is a header of
four locators pointing at the character info, animation, image and audio
tables. Frame bitmaps are 8-bit paletted and stored with Agent's own bit-level
LZ77-style compressor.

Only what a thumbnail needs is parsed -- the first image frame and the palette.
Animations, audio, branching and voice data are skipped.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = 0xABCDABC3


class AcsError(Exception):
    pass


def decompress(src: bytes, expected: int) -> bytes:
    """Agent's bit-level compressor, per the spec's Compression Algorithm.

    The stream is a leading 0x00, the bit stream, then six 0xFF bytes. Bits are
    taken from each byte least-significant first. A 0 flag introduces one
    literal byte; a 1 flag introduces a back-reference copied from what has
    already been decompressed, which may overlap the insertion point and so is
    copied one byte at a time.
    """
    if not src:
        raise AcsError("empty compressed block")
    pos, bit = 1, 0  # skip the leading 0x00
    out = bytearray()

    def read_bit() -> int:
        nonlocal pos, bit
        if pos >= len(src):
            raise AcsError("bit stream overrun")
        v = (src[pos] >> bit) & 1
        bit += 1
        if bit == 8:
            bit, pos = 0, pos + 1
        return v

    def read_val(n: int) -> int:
        """n bits, first bit read is the least significant."""
        v = 0
        for i in range(n):
            v |= read_bit() << i
        return v

    def count_ones(limit: int) -> int:
        """Sequential 1-bits, consuming the terminating 0 unless limit hit."""
        n = 0
        while n < limit:
            if read_bit() == 0:
                return n
            n += 1
        return n

    # Offset width and bias are selected by how many 1-bits lead the sequence.
    WIDTHS = {0: (6, 0x0001), 1: (9, 0x0041), 2: (12, 0x0241), 3: (20, 0x1241)}

    while len(out) < expected:
        if read_bit() == 0:
            out.append(read_val(8))
            continue

        seq = count_ones(3)
        width, bias = WIDTHS[seq]
        raw = read_val(width)
        if width == 20 and raw == 0x000FFFFF:
            break  # end of stream
        offset = raw + bias
        count = 2 + (1 if width == 20 else 0)

        # A run of m 1-bits contributes 2**m - 1, then m further bits are read
        # and added -- so short runs stay cheap and long ones stay expressible.
        m = count_ones(11)
        if m >= 11 and read_bit() == 1:
            raise AcsError("malformed length prefix")
        count += (1 << m) - 1
        if m:
            count += read_val(m)

        if offset > len(out):
            raise AcsError(f"back-reference {offset} beyond {len(out)} bytes")
        start = len(out) - offset
        for i in range(count):
            out.append(out[start + i])

    return bytes(out[:expected])


def _row_stride(width: int) -> int:
    """Rows are padded up to a 4-byte boundary."""
    return (width + 3) & ~3


@dataclass
class Frame:
    width: int
    height: int
    pixels: bytes          # width*height, top-left origin, palette indices
    palette: list          # list of (r, g, b)
    transparent: int       # palette index treated as transparent


def _read_locator(buf: bytes, off: int) -> tuple:
    return struct.unpack_from("<II", buf, off)


def _find_palette(block: bytes) -> tuple:
    """Locate the colour table inside ACSCHARACTERINFO.

    VOICEINFO sits between the fixed fields and the palette and is variable
    length, so rather than walk it, look for a plausible table: a count of
    entries followed by that many RGBQUADs, whose reserved 4th byte is always
    zero. 256 entries is the common case, so prefer the first such run.
    """
    for count in (256, 128, 64, 16, 2):
        needle = struct.pack("<I", count)
        start = 0
        while True:
            i = block.find(needle, start)
            if i < 0:
                break
            body = i + 4
            end = body + count * 4
            if end <= len(block) and all(
                block[body + k * 4 + 3] == 0 for k in range(count)
            ):
                pal = [
                    (block[body + k * 4 + 2], block[body + k * 4 + 1],
                     block[body + k * 4])
                    for k in range(count)
                ]
                # An all-black table is almost certainly a false positive.
                if any(c != (0, 0, 0) for c in pal):
                    return pal, body
            start = i + 1
    raise AcsError("no colour table found")


def first_frame(data: bytes) -> Frame:
    """Decode the character's first image frame."""
    if len(data) < 36:
        raise AcsError("too short for an ACS header")
    sig, = struct.unpack_from("<I", data, 0)
    if sig != MAGIC:
        raise AcsError(f"bad signature 0x{sig:08x}")

    char_off, char_size = _read_locator(data, 4)
    img_off, img_size = _read_locator(data, 20)

    if not (0 < img_off < len(data)) or img_size < 4:
        raise AcsError("no image table")
    table = data[img_off:img_off + img_size]
    count, = struct.unpack_from("<I", table, 0)
    if count == 0:
        raise AcsError("character has no images")
    # Each entry is a locator plus a checksum.
    entry_off, entry_size = struct.unpack_from("<II", table, 4)
    if not (0 < entry_off < len(data)):
        raise AcsError("image entry outside file")

    blk = data[entry_off:entry_off + entry_size]
    if len(blk) < 10:
        raise AcsError("truncated image entry")
    # BYTE unknown, USHORT width, USHORT height, BYTE flags, ULONG data size.
    width, height = struct.unpack_from("<HH", blk, 1)
    comp_size, = struct.unpack_from("<I", blk, 6)
    if width <= 0 or height <= 0 or width > 4096 or height > 4096:
        raise AcsError(f"implausible frame {width}x{height}")

    stride = _row_stride(width)
    raw_len = stride * height
    payload = blk[10:10 + comp_size] if comp_size else blk[10:10 + raw_len]
    raw = decompress(payload, raw_len) if comp_size else payload
    if len(raw) < raw_len:
        raise AcsError(f"short bitmap: {len(raw)} of {raw_len}")

    char = data[char_off:char_off + char_size]
    palette, _ = _find_palette(char)
    transparent = char[32] if len(char) > 32 else 0

    # Bitmaps are bottom-up; flip to a top-left origin and drop row padding.
    rows = [raw[y * stride:y * stride + width] for y in range(height)]
    rows.reverse()
    return Frame(width, height, b"".join(rows), palette, transparent)


# --- thumbnail output -------------------------------------------------------
#
# A tiny PNG writer, so rendering needs nothing outside the standard library.
# CI then requires no image dependency at all.

import zlib


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def write_png(path, rgba: bytes, width: int, height: int) -> None:
    """Write 8-bit RGBA pixels as a PNG."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: none
        raw += rgba[y * width * 4:(y + 1) * width * 4]
    body = (_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + body)


def to_rgba(frame: Frame) -> bytes:
    """Palette indices -> RGBA, with the transparent index made fully clear."""
    pal = frame.palette
    out = bytearray(len(frame.pixels) * 4)
    for i, idx in enumerate(frame.pixels):
        if idx == frame.transparent:
            continue  # leave as transparent black
        r, g, b = pal[idx] if idx < len(pal) else (0, 0, 0)
        o = i * 4
        out[o] = r
        out[o + 1] = g
        out[o + 2] = b
        out[o + 3] = 255
    return bytes(out)


def thumbnail(rgba: bytes, width: int, height: int, box: int):
    """Box-filter down so the longest side is `box`, preserving aspect.

    Averaging over each source region rather than point-sampling matters here:
    these sprites have single-pixel outlines that nearest-neighbour drops,
    leaving the shape looking broken at small sizes. Alpha-weighted so
    transparent pixels don't bleed dark edges into the result.
    """
    if max(width, height) <= box:
        return rgba, width, height
    scale = box / max(width, height)
    tw, th = max(1, round(width * scale)), max(1, round(height * scale))
    out = bytearray(tw * th * 4)
    for ty in range(th):
        y0, y1 = ty * height // th, max(ty * height // th + 1, (ty + 1) * height // th)
        for tx in range(tw):
            x0, x1 = tx * width // tw, max(tx * width // tw + 1, (tx + 1) * width // tw)
            r = g = b = a = n = 0
            for y in range(y0, y1):
                base = y * width
                for x in range(x0, x1):
                    o = (base + x) * 4
                    av = rgba[o + 3]
                    r += rgba[o] * av
                    g += rgba[o + 1] * av
                    b += rgba[o + 2] * av
                    a += av
                    n += 1
            o = (ty * tw + tx) * 4
            if a:
                out[o] = min(255, r // a)
                out[o + 1] = min(255, g // a)
                out[o + 2] = min(255, b // a)
                out[o + 3] = a // n
    return bytes(out), tw, th
