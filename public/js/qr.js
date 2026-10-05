/* Minimal QR Code encoder (byte mode, error correction M, versions 1-10).
   window.IconiqQR.matrix(text) -> array of rows of booleans (true = dark). */

(function () {
  "use strict";

  // Per version (index = version): [data codewords per block group..., ec codewords per block]
  // Each entry: { ec: EC codewords per block, groups: [[blockCount, dataCodewordsPerBlock], ...] }
  var SPEC = [null,
    { ec: 10, groups: [[1, 16]] },
    { ec: 16, groups: [[1, 28]] },
    { ec: 26, groups: [[1, 44]] },
    { ec: 18, groups: [[2, 32]] },
    { ec: 24, groups: [[2, 43]] },
    { ec: 16, groups: [[4, 27]] },
    { ec: 18, groups: [[4, 31]] },
    { ec: 22, groups: [[2, 38], [2, 39]] },
    { ec: 22, groups: [[3, 36], [2, 37]] },
    { ec: 26, groups: [[4, 43], [1, 44]] }
  ];
  var ALIGN = [null, [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]];

  // ---- Reed-Solomon over GF(256) ----
  var EXP = [], LOG = [];
  (function () {
    var x = 1;
    for (var i = 0; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 256) x ^= 0x11d; }
    for (i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
  })();

  function rsEncode(data, ecLen) {
    var gen = [1], i, j;
    for (i = 0; i < ecLen; i++) {
      var next = new Array(gen.length + 1).fill(0);
      for (j = 0; j < gen.length; j++) {
        next[j] ^= gen[j];
        next[j + 1] ^= EXP[(LOG[gen[j]] + i) % 255];
      }
      gen = next;
    }
    var res = data.concat(new Array(ecLen).fill(0));
    for (i = 0; i < data.length; i++) {
      var f = res[i];
      if (f) for (j = 1; j < gen.length; j++) res[i + j] ^= EXP[(LOG[gen[j]] + LOG[f]) % 255];
    }
    return res.slice(data.length);
  }

  function bch(value, poly, bits) {
    var msb = function (n) { var k = 0; while (n) { k++; n >>= 1; } return k; }, v = value << bits, pl = msb(poly);
    while (msb(v) >= pl) v ^= poly << (msb(v) - pl);
    return v;
  }

  function utf8(text) {
    var s = unescape(encodeURIComponent(text)), out = [];
    for (var i = 0; i < s.length; i++) out.push(s.charCodeAt(i));
    return out;
  }

  // ---- Codewords ----
  function codewords(bytes) {
    var v, cap;
    for (v = 1; v <= 10; v++) {
      cap = SPEC[v].groups.reduce(function (a, g) { return a + g[0] * g[1]; }, 0);
      if (bytes.length + (v < 10 ? 2 : 3) <= cap) break;
    }
    if (v > 10) throw new Error("QR text too long");

    var bits = [];
    function put(val, len) { for (var i = len - 1; i >= 0; i--) bits.push((val >> i) & 1); }
    put(4, 4); put(bytes.length, v < 10 ? 8 : 16);
    bytes.forEach(function (b) { put(b, 8); });
    for (var t = 0; t < 4 && bits.length < cap * 8; t++) bits.push(0);
    while (bits.length % 8) bits.push(0);
    var data = [];
    for (var i = 0; i < bits.length; i += 8) {
      var n = 0;
      for (var k = 0; k < 8; k++) n = (n << 1) | bits[i + k];
      data.push(n);
    }
    for (var pad = 0; data.length < cap; pad++) data.push(pad % 2 ? 0x11 : 0xec);

    var blocks = [], ecs = [], pos = 0;
    SPEC[v].groups.forEach(function (g) {
      for (var b = 0; b < g[0]; b++) {
        var d = data.slice(pos, pos + g[1]); pos += g[1];
        blocks.push(d); ecs.push(rsEncode(d, SPEC[v].ec));
      }
    });
    var out = [], max = Math.max.apply(null, blocks.map(function (b) { return b.length; }));
    for (i = 0; i < max; i++) blocks.forEach(function (b) { if (i < b.length) out.push(b[i]); });
    for (i = 0; i < SPEC[v].ec; i++) ecs.forEach(function (e) { out.push(e[i]); });
    return { version: v, words: out };
  }

  // ---- Matrix ----
  var MASKS = [
    function (r, c) { return (r + c) % 2 === 0; },
    function (r) { return r % 2 === 0; },
    function (r, c) { return c % 3 === 0; },
    function (r, c) { return (r + c) % 3 === 0; },
    function (r, c) { return (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0; },
    function (r, c) { return (r * c) % 2 + (r * c) % 3 === 0; },
    function (r, c) { return ((r * c) % 2 + (r * c) % 3) % 2 === 0; },
    function (r, c) { return ((r * c) % 3 + (r + c) % 2) % 2 === 0; }
  ];

  function build(version, words, mask) {
    var n = 17 + 4 * version, m = [], fixed = [], r, c, i;
    for (r = 0; r < n; r++) { m.push(new Array(n).fill(false)); fixed.push(new Array(n).fill(false)); }
    function set(r, c, dark) { m[r][c] = dark; fixed[r][c] = true; }

    function finder(r0, c0) {
      for (var y = -1; y <= 7; y++) for (var x = -1; x <= 7; x++) {
        var rr = r0 + y, cc = c0 + x;
        if (rr < 0 || cc < 0 || rr >= n || cc >= n) continue;
        var dark = (y >= 0 && y <= 6 && (x === 0 || x === 6)) || (x >= 0 && x <= 6 && (y === 0 || y === 6)) ||
                   (y >= 2 && y <= 4 && x >= 2 && x <= 4);
        set(rr, cc, dark);
      }
    }
    finder(0, 0); finder(n - 7, 0); finder(0, n - 7);

    for (i = 8; i < n - 8; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }

    var al = ALIGN[version];
    al.forEach(function (ar) { al.forEach(function (ac) {
      if (fixed[ar][ac]) return; // overlaps a finder pattern
      for (var y = -2; y <= 2; y++) for (var x = -2; x <= 2; x++)
        set(ar + y, ac + x, Math.max(Math.abs(x), Math.abs(y)) !== 1);
    }); });

    // Reserve format / version areas
    for (i = 0; i < 9; i++) { fixed[8][i] = true; fixed[i][8] = true; }
    for (i = 0; i < 8; i++) { fixed[8][n - 1 - i] = true; fixed[n - 1 - i][8] = true; }
    if (version >= 7) for (i = 0; i < 6; i++) for (c = 0; c < 3; c++) { fixed[i][n - 11 + c] = true; fixed[n - 11 + c][i] = true; }

    // Data, zig-zag from the bottom-right
    var bits = [];
    words.forEach(function (w) { for (var k = 7; k >= 0; k--) bits.push((w >> k) & 1); });
    var bi = 0, up = true;
    for (c = n - 1; c > 0; c -= 2) {
      if (c === 6) c--;
      for (var step = 0; step < n; step++) {
        r = up ? n - 1 - step : step;
        for (var dc = 0; dc < 2; dc++) {
          var cc = c - dc;
          if (fixed[r][cc]) continue;
          var bit = bi < bits.length ? bits[bi++] === 1 : false;
          m[r][cc] = MASKS[mask](r, cc) ? !bit : bit;
        }
      }
      up = !up;
    }

    // Format info (error correction M = 00) and dark module
    var fmt = (((0 << 3) | mask) << 10 | bch((0 << 3) | mask, 0x537, 10)) ^ 0x5412;
    for (i = 0; i < 15; i++) {
      var d = ((fmt >> i) & 1) === 1;
      if (i < 6) m[i][8] = d; else if (i < 8) m[i + 1][8] = d; else m[n - 15 + i][8] = d;
      if (i < 8) m[8][n - i - 1] = d; else if (i < 9) m[8][15 - i] = d; else m[8][14 - i] = d;
    }
    m[n - 8][8] = true;

    if (version >= 7) {
      var vi = (version << 12) | bch(version, 0x1f25, 12);
      for (i = 0; i < 18; i++) {
        var vd = ((vi >> i) & 1) === 1;
        m[Math.floor(i / 3)][i % 3 + n - 11] = vd;
        m[i % 3 + n - 11][Math.floor(i / 3)] = vd;
      }
    }
    return m;
  }

  function penalty(m) {
    var n = m.length, p = 0, r, c, run, i;
    function lines(get) {
      for (var a = 0; a < n; a++) {
        run = 1;
        for (var b = 1; b < n; b++) {
          if (get(a, b) === get(a, b - 1)) { run++; if (run === 5) p += 3; else if (run > 5) p++; } else run = 1;
        }
        // finder-like 1:1:3:1:1 with 4 light modules on either side
        for (b = 0; b + 10 < n; b++) {
          var s = "";
          for (i = 0; i < 11; i++) s += get(a, b + i) ? "1" : "0";
          if (s === "10111010000" || s === "00001011101") p += 40;
        }
      }
    }
    lines(function (a, b) { return m[a][b]; });
    lines(function (a, b) { return m[b][a]; });
    var dark = 0;
    for (r = 0; r < n; r++) for (c = 0; c < n; c++) {
      if (m[r][c]) dark++;
      if (r && c && m[r][c] === m[r - 1][c] && m[r][c] === m[r][c - 1] && m[r][c] === m[r - 1][c - 1]) p += 3;
    }
    p += Math.floor(Math.abs(dark * 100 / (n * n) - 50) / 5) * 10;
    return p;
  }

  function matrix(text) {
    var cw = codewords(utf8(text)), best = null, bestP = Infinity;
    for (var mask = 0; mask < 8; mask++) {
      var m = build(cw.version, cw.words, mask), p = penalty(m);
      if (p < bestP) { bestP = p; best = m; }
    }
    return best;
  }

  window.IconiqQR = { matrix: matrix };
})();
