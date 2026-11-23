"""Generate packaging/app.ico (no image libraries needed): an 8-point star
(rub el hizb) in gold with an emerald centre on a dark rounded tile."""
import math
import struct
import zlib
from pathlib import Path


def render(size: int) -> bytes:
    px = bytearray()
    c = (size - 1) / 2
    r_tile = size * 0.22
    for y in range(size):
        px.append(0)  # PNG filter byte
        for x in range(size):
            # rounded square tile
            dx = max(abs(x - c) - (c - r_tile), 0)
            dy = max(abs(y - c) - (c - r_tile), 0)
            inside = math.hypot(dx, dy) <= r_tile
            if not inside:
                px += bytes((0, 0, 0, 0))
                continue
            col = (15, 26, 22, 255)
            rx, ry = (x - c) / c, (y - c) / c
            dist = math.hypot(rx, ry)
            ang = math.atan2(ry, rx)
            # 8-point star = union of two rotated squares
            def sq(a):
                ca, sa = math.cos(a), math.sin(a)
                u, v = rx * ca + ry * sa, -rx * sa + ry * ca
                return max(abs(u), abs(v))
            star = min(sq(0), sq(math.pi / 4))
            if 0.5 <= star <= 0.62:
                col = (217, 180, 91, 255)
            if dist <= 0.27:
                col = (63, 182, 139, 255)
            _ = ang
            px += bytes(col)
    raw = bytes(px)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def main():
    sizes = [16, 32, 48, 64, 128, 256]
    images = [render(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for s, img in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
    out = Path(__file__).with_name("app.ico")
    out.write_bytes(header + entries + b"".join(images))
    print(out)


if __name__ == "__main__":
    main()
