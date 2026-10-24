VERSIONS = {
    1: (26, 7, [(1, 19)]),
    2: (44, 10, [(1, 34)]),
    3: (70, 15, [(1, 55)]),
    4: (100, 20, [(1, 80)]),
    5: (134, 26, [(1, 108)]),
    6: (172, 18, [(2, 68)]),
    7: (196, 20, [(2, 78)]),
    8: (242, 24, [(2, 97)]),
    9: (292, 30, [(2, 116)]),
    10: (346, 18, [(2, 68), (2, 69)]),
}

ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

EXP = [0] * 512
LOG = [0] * 256
_x = 1
for _i in range(255):
    EXP[_i] = _x
    LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    EXP[_i] = EXP[_i - 255]


def gmul(a, b):
    if a == 0 or b == 0:
        return 0
    return EXP[LOG[a] + LOG[b]]


def generator(n):
    g = [1]
    for i in range(n):
        nxt = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            nxt[j] ^= c
            nxt[j + 1] ^= gmul(c, EXP[i])
        g = nxt
    return g


def ec_bytes(data, n):
    g = generator(n)
    rem = list(data) + [0] * n
    for i in range(len(data)):
        c = rem[i]
        if c:
            for j in range(1, len(g)):
                rem[i + j] ^= gmul(g[j], c)
    return rem[len(data):]


def bch(value, poly, bits):
    v = value << bits
    top = poly.bit_length() - 1
    while v.bit_length() > top:
        v ^= poly << (v.bit_length() - poly.bit_length())
    return (value << bits) | v


def pick_version(n):
    for v in range(1, 11):
        total, ec, groups = VERSIONS[v]
        cap = sum(c * d for c, d in groups)
        count_bits = 8 if v < 10 else 16
        if 4 + count_bits + 8 * n <= cap * 8:
            return v
    raise ValueError("too long for a qr code here")


def codewords(data, v):
    total, ec, groups = VERSIONS[v]
    cap = sum(c * d for c, d in groups)
    bits = "0100" + format(len(data), "08b" if v < 10 else "016b")
    bits += "".join(format(b, "08b") for b in data)
    bits += "0" * min(4, cap * 8 - len(bits))
    bits += "0" * (-len(bits) % 8)
    out = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    k = 0
    while len(out) < cap:
        out.append(0xEC if k % 2 == 0 else 0x11)
        k += 1
    blocks, i = [], 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(out[i:i + size])
            i += size
    ecs = [ec_bytes(b, ec) for b in blocks]
    res = []
    for k in range(max(len(b) for b in blocks)):
        for b in blocks:
            if k < len(b):
                res.append(b[k])
    for k in range(ec):
        for e in ecs:
            res.append(e[k])
    return res


def base(v):
    n = 17 + 4 * v
    m = [[None] * n for _ in range(n)]

    def finder(r, c):
        for y in range(-1, 8):
            for x in range(-1, 8):
                if 0 <= r + y < n and 0 <= c + x < n:
                    on = 0 <= y <= 6 and 0 <= x <= 6 and (y in (0, 6) or x in (0, 6) or (2 <= y <= 4 and 2 <= x <= 4))
                    m[r + y][c + x] = on

    finder(0, 0)
    finder(0, n - 7)
    finder(n - 7, 0)
    for i in range(8, n - 8):
        m[6][i] = i % 2 == 0
        m[i][6] = i % 2 == 0
    pos = ALIGN[v]
    for r in pos:
        for c in pos:
            if (r < 9 and c < 9) or (r < 9 and c > n - 9) or (r > n - 9 and c < 9):
                continue
            for y in range(-2, 3):
                for x in range(-2, 3):
                    m[r + y][c + x] = max(abs(y), abs(x)) != 1
    m[n - 8][8] = True
    for i in range(9):
        if m[8][i] is None:
            m[8][i] = False
        if m[i][8] is None:
            m[i][8] = False
    for i in range(8):
        if m[8][n - 1 - i] is None:
            m[8][n - 1 - i] = False
        if m[n - 1 - i][8] is None:
            m[n - 1 - i][8] = False
    if v >= 7:
        info = bch(v, 0x1F25, 12)
        for i in range(18):
            bit = bool((info >> i) & 1)
            a, b = i // 3, n - 11 + i % 3
            m[a][b] = bit
            m[b][a] = bit
    return m


MASKS = [
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
]


def place(m, words, mask):
    n = len(m)
    out = [row[:] for row in m]
    bits = [(w >> (7 - i)) & 1 for w in words for i in range(8)]
    k = 0
    c = n - 1
    up = True
    while c > 0:
        if c == 6:
            c -= 1
        rows = range(n - 1, -1, -1) if up else range(n)
        for r in rows:
            for cc in (c, c - 1):
                if m[r][cc] is None:
                    bit = bits[k] if k < len(bits) else 0
                    k += 1
                    out[r][cc] = bool(bit) ^ MASKS[mask](r, cc)
        up = not up
        c -= 2
    fmt = bch((0b01 << 3) | mask, 0x537, 10) ^ 0x5412
    bit = [bool((fmt >> i) & 1) for i in range(15)]
    for i in range(6):
        out[i][8] = bit[i]
    out[7][8] = bit[6]
    out[8][8] = bit[7]
    out[8][7] = bit[8]
    for i in range(9, 15):
        out[8][14 - i] = bit[i]
    for i in range(8):
        out[8][n - 1 - i] = bit[i]
    for i in range(8, 15):
        out[n - 15 + i][8] = bit[i]
    return out


def penalty(m):
    n = len(m)
    score = 0
    for grid in (m, [list(col) for col in zip(*m)]):
        for row in grid:
            run, prev = 0, None
            for v in row:
                if v == prev:
                    run += 1
                else:
                    if run >= 5:
                        score += run - 2
                    run, prev = 1, v
            if run >= 5:
                score += run - 2
            s = "".join("1" if v else "0" for v in row)
            score += 40 * (s.count("10111010000") + s.count("00001011101"))
    for r in range(n - 1):
        for c in range(n - 1):
            v = m[r][c]
            if v == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    dark = sum(v for row in m for v in row)
    score += 10 * (abs(dark * 100 // (n * n) - 50) // 5)
    return score


def encode(text):
    data = text.encode()
    v = pick_version(len(data))
    words = codewords(data, v)
    b = base(v)
    best = min((place(b, words, k) for k in range(8)), key=penalty)
    return best


def terminal(text, invert=True):
    m = encode(text)
    n = len(m)
    q = 2
    grid = [[False] * (n + 2 * q) for _ in range(n + 2 * q)]
    for r in range(n):
        for c in range(n):
            grid[r + q][c + q] = m[r][c]
    if len(grid) % 2:
        grid.append([False] * len(grid[0]))
    lines = []
    for r in range(0, len(grid), 2):
        line = ""
        for c in range(len(grid[0])):
            top, bot = grid[r][c], grid[r + 1][c]
            if invert:
                top, bot = not top, not bot
            line += {(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}[(top, bot)]
        lines.append(line)
    return "\n".join(lines)


def svg(text, scale=8, fg="#000", bg="#fff"):
    m = encode(text)
    n = len(m)
    q = 4
    size = (n + 2 * q) * scale
    rects = []
    for r in range(n):
        c = 0
        while c < n:
            if m[r][c]:
                s = c
                while c < n and m[r][c]:
                    c += 1
                rects.append(f'<rect x="{(s + q) * scale}" y="{(r + q) * scale}" width="{(c - s) * scale}" height="{scale}"/>')
            else:
                c += 1
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
        f'<rect width="{size}" height="{size}" fill="{bg}"/><g fill="{fg}">{"".join(rects)}</g></svg>'
    )
