// make-icons.js —— 生成扩展图标（16 / 48 / 128）。
//
// 为什么自己写 PNG 编码：
//   这台机器没装 ImageMagick / sharp，也不该为了三个图标去装依赖。
//   PNG 的最小实现只有"签名 + IHDR + IDAT + IEND"四块，
//   IDAT 用 Node 自带的 zlib 压缩即可 —— 几十行就够。
//
// 图标设计（对应产品本身）：
//   深色圆角底 + 三条"文字行" + 中间一条高亮
//   —— 就是"按句高亮"这件事本身，一眼能看懂，16px 下也认得出。
//
// 抗锯齿：先在 4 倍尺寸上画，再降采样。比直接画锯齿边好看得多。
//
// 用法： node tools/make-icons.js

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

// ---------------------------------------------------------------- PNG 编码
const CRC_TABLE = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
    t[n] = c;
  }
  return t;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const td = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(td), 0);
  return Buffer.concat([len, td, crc]);
}

function encodePNG(w, h, rgba) {
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8;      // 位深
  ihdr[9] = 6;      // 颜色类型 RGBA
  ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  const stride = w * 4;
  const raw = Buffer.alloc((stride + 1) * h);
  for (let y = 0; y < h; y++) {
    raw[y * (stride + 1)] = 0;                    // filter: none
    rgba.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
  }
  return Buffer.concat([
    sig,
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

// ---------------------------------------------------------------- 画图
// 尺寸 s 的画布，用浮点覆盖法抗锯齿（在 4 倍超采样下直接当成填充用）
const SS = 4;   // 超采样倍数

function makeCanvas(size) {
  const n = size * SS;
  const px = new Float64Array(n * n * 4);   // r,g,b,a（0..1）
  return { n: n, px: px };
}

function blend(c, x, y, r, g, b, a) {
  if (x < 0 || y < 0 || x >= c.n || y >= c.n || a <= 0) return;
  const i = (y * c.n + x) * 4;
  const ia = 1 - a;
  c.px[i]     = c.px[i]     * ia + r * a;
  c.px[i + 1] = c.px[i + 1] * ia + g * a;
  c.px[i + 2] = c.px[i + 2] * ia + b * a;
  c.px[i + 3] = c.px[i + 3] * ia + a;
}

// 圆角矩形（坐标是 0..1 的相对值）
function roundRect(c, x0, y0, x1, y1, rad, r, g, b, a) {
  const X0 = x0 * c.n, Y0 = y0 * c.n, X1 = x1 * c.n, Y1 = y1 * c.n;
  const R = rad * c.n;
  for (let y = Math.floor(Y0); y < Math.ceil(Y1); y++) {
    for (let x = Math.floor(X0); x < Math.ceil(X1); x++) {
      const cx = Math.min(Math.max(x + 0.5, X0 + R), X1 - R);
      const cy = Math.min(Math.max(y + 0.5, Y0 + R), Y1 - R);
      const dx = x + 0.5 - cx, dy = y + 0.5 - cy;
      if (dx * dx + dy * dy <= R * R) blend(c, x, y, r, g, b, a);
    }
  }
}

function downsample(c, size) {
  const out = Buffer.alloc(size * size * 4);
  const k = SS * SS;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let r = 0, g = 0, b = 0, a = 0;
      for (let dy = 0; dy < SS; dy++) {
        for (let dx = 0; dx < SS; dx++) {
          const i = ((y * SS + dy) * c.n + (x * SS + dx)) * 4;
          const ai = c.px[i + 3];
          // 预乘 alpha 再加权，否则透明边缘会发黑
          r += c.px[i] * ai; g += c.px[i + 1] * ai; b += c.px[i + 2] * ai; a += ai;
        }
      }
      const o = (y * size + x) * 4;
      if (a > 0) {
        out[o]     = Math.round(Math.min(1, r / a) * 255);
        out[o + 1] = Math.round(Math.min(1, g / a) * 255);
        out[o + 2] = Math.round(Math.min(1, b / a) * 255);
      }
      out[o + 3] = Math.round(Math.min(1, a / k) * 255);
    }
  }
  return out;
}

// 画一个尺寸的图标
function drawIcon(size) {
  const c = makeCanvas(size);
  const small = size <= 16;

  // 底色：深蓝灰（和面板配色一致）
  roundRect(c, 0.02, 0.02, 0.98, 0.98, 0.22, 0.11, 0.13, 0.18, 1);

  // 三条"文字行"。小尺寸下减少到两条，否则糊成一团。
  const lineH = small ? 0.13 : 0.11;
  const rows = small ? [0.30, 0.62] : [0.28, 0.46, 0.64];
  rows.forEach((cy, i) => {
    const left = 0.18;
    const right = (i === 1) ? 0.82 : 0.72;      // 中间那行最长
    roundRect(c, left, cy - lineH / 2, right, cy + lineH / 2, lineH / 2,
              0.78, 0.81, 0.86, 1);
  });

  // 高亮条：盖在中间那行上（这就是产品在做的事）
  const hi = small ? 0.62 : 0.46;
  roundRect(c, 0.13, hi - lineH * 0.78, 0.87, hi + lineH * 0.78, lineH * 0.78,
            0.36, 0.55, 0.94, 1);

  return downsample(c, size);
}

// ---------------------------------------------------------------- 主程序
const OUT = path.resolve(__dirname, '..', 'plugin', 'icons');
fs.mkdirSync(OUT, { recursive: true });

const sizes = [16, 48, 128];
sizes.forEach(sz => {
  const rgba = drawIcon(sz);
  const png = encodePNG(sz, sz, rgba);
  const f = path.join(OUT, 'icon' + sz + '.png');
  fs.writeFileSync(f, png);
  console.log('  ' + path.basename(f) + '  ' + sz + 'x' + sz + '  ' + png.length + ' 字节');
});

// ------------------------------------------------------------------
//  商店列表用的 logo
//
//  商店要求：推荐 300×300，最小 128×128，并且要【有留白】。
//  直接拿 icon128.png 上传虽然过得了最小值，但那个图形是顶满画布的，
//  商店自己的圆角/裁切一处理就会显得挤 —— 所以单独出一张带留白的。
//
//  做法：画一个 300×300 的画布，里面按 78% 的比例居中放图标，
//  四周留出透明边距。透明而不是白底 —— 商店可能放在深色页面上。
// ------------------------------------------------------------------
function drawLogo(size, innerRatio) {
  const c = makeCanvas(size);
  const pad = (1 - innerRatio) / 2;
  const small = false;

  // 底：圆角方块（按 innerRatio 缩放并居中）
  roundRect(c, pad + 0.02 * innerRatio, pad + 0.02 * innerRatio,
            pad + 0.98 * innerRatio, pad + 0.98 * innerRatio,
            0.22 * innerRatio, 0.11, 0.13, 0.18, 1);

  const lineH = 0.11 * innerRatio;
  const rows = [0.28, 0.46, 0.64];
  rows.forEach((cy, i) => {
    const y = pad + cy * innerRatio;
    const left = pad + 0.18 * innerRatio;
    const right = pad + ((i === 1) ? 0.82 : 0.72) * innerRatio;
    roundRect(c, left, y - lineH / 2, right, y + lineH / 2, lineH / 2,
              0.78, 0.81, 0.86, 1);
  });

  const hi = pad + 0.46 * innerRatio;
  roundRect(c, pad + 0.13 * innerRatio, hi - lineH * 0.78,
            pad + 0.87 * innerRatio, hi + lineH * 0.78, lineH * 0.78,
            0.36, 0.55, 0.94, 1);

  return downsample(c, size);
}

const LOGO_OUT = path.resolve(__dirname, '..', 'store');
fs.mkdirSync(LOGO_OUT, { recursive: true });
[300, 128].forEach(sz => {
  const rgba = drawLogo(sz, 0.78);
  const png = encodePNG(sz, sz, rgba);
  const f = path.join(LOGO_OUT, 'store-logo-' + sz + '.png');
  fs.writeFileSync(f, png);
  console.log('  ' + path.basename(f) + '  ' + sz + 'x' + sz + '  ' + png.length + ' 字节');
});

console.log('\n  扩展图标已生成到 plugin/icons/');
console.log('  商店 logo   已生成到 store/（带留白，上传这一张）');
