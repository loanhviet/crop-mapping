/** Render locally; application code and application dependencies are not modified. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';

const root = path.dirname(fileURLToPath(import.meta.url));
const toolDir = process.env.REPORT_TOOLS_DIR || '/tmp/crop-map-report-tools';
const req = createRequire(path.join(toolDir, 'package.json'));
const puppeteer = req('puppeteer');
const cli = path.join(toolDir, 'node_modules/.bin/mmdc');
const config = JSON.parse(await fs.readFile(path.join(root, 'nguon/noi-dung.json'), 'utf8'));
const escape = s => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');

for (const folder of ['hinh/svg', 'hinh/png', 'hinh/pdf']) {
  await fs.mkdir(path.join(root, folder), { recursive: true });
}

if (!process.argv.includes('--skip-render')) {
  for (const figure of config.figures) {
    const input = path.join(root, 'nguon', figure.id);
    const output = path.join(root, 'hinh/svg', figure.id + '.svg');
    try {
      await fs.access(input + '.puml');
      execFileSync('java', ['-Djava.awt.headless=true', '-jar', path.join(toolDir, 'plantuml.jar'), '-tsvg', '-charset', 'UTF-8', '-o', '../hinh/svg', input + '.puml'], { stdio: 'pipe' });
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      execFileSync(cli, ['-i', input + '.mmd', '-o', output, '-c', path.join(root, 'nguon/mermaid-config.json'), '-p', path.join(root, 'nguon/puppeteer-config.json'), '-b', 'white'], { stdio: 'pipe' });
    }
    console.log('SVG', figure.id);
  }
}

const browser = await puppeteer.launch({ executablePath: process.env.REPORT_CHROME || '/usr/bin/google-chrome', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage();
const manifest = [];
try {
  for (const [index, figure] of config.figures.entries()) {
    const svgPath = path.join(root, 'hinh/svg', figure.id + '.svg');
    const svg = await fs.readFile(svgPath, 'utf8');
    if (svg.includes('Syntax Error') || svg.includes('Cannot find Graphviz')) throw new Error('Invalid SVG: ' + figure.id);
    const match = svg.match(/viewBox="([^"]+)"/);
    if (!match) throw new Error('Missing viewBox: ' + figure.id);
    const [, , width, height] = match[1].split(/\s+/).map(Number);
    // Render the actual diagram to an image with at least 2400 px on its long edge.
    const scale = Math.max(1, Math.min(2.5, 3000 / Math.max(width, height)));
    await page.setViewport({ width: Math.ceil(width + 24), height: Math.ceil(height + 24), deviceScaleFactor: scale });
    await page.setContent(`<html><head><meta charset="utf-8"><style>body{margin:0;padding:12px;background:white}svg{display:block;width:${width}px!important;height:${height}px!important;max-width:none!important}</style></head><body>${svg}</body></html>`, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.join(root, 'hinh/png', figure.id + '.png'), fullPage: true });
    const portrait = height > width * 1.12;
    // The two largest UML/state figures use A2; others use A3 for readable review.
    const paper = width > 2400 || height > 2700 ? 'A2' : 'A3';
    const [shortMM, longMM] = paper === 'A2' ? [420, 594] : [297, 420];
    const pageWidthMM = portrait ? shortMM : longMM;
    const pageHeightMM = portrait ? longMM : shortMM;
    const cssHeight = paper === 'A2' ? (portrait ? 2245 : 1587) : (portrait ? 1587 : 1122);
    const imageHeight = cssHeight - 420;
    await page.setViewport({ width: 1500, height: 1100, deviceScaleFactor: 1 });
    const sheet = `<!doctype html><html lang="vi"><head><meta charset="utf-8"><style>
      @page{size:${pageWidthMM}mm ${pageHeightMM}mm;margin:14mm}
      body{font-family:"DejaVu Sans",Arial,sans-serif;color:#111827;margin:0;font-size:12pt}
      h1{font-size:18pt;margin:0 0 5mm} .tag{font-size:10pt;color:#475569;margin:0 0 5mm}
      .drawing{height:${imageHeight}px;display:flex;align-items:center;justify-content:center}
      .drawing img{max-height:100%;max-width:100%;object-fit:contain}
      .caption{font-size:12pt;line-height:1.45;margin:5mm 0 2mm}
      .source{font-size:9pt;color:#475569;line-height:1.4}
    </style></head><body><h1>Hình ${index + 1}. ${escape(figure.title)}</h1>
      <p class="tag">${escape(figure.type)} · ${index === config.figures.length - 1 ? 'Nhánh tùy chọn' : 'Luồng chính: prepared'} · Đối chiếu ${config.date}</p>
      <div class="drawing"><img src="${pathToFileURL(svgPath).href}"></div>
      <p class="caption">${escape(figure.caption)}</p><p class="source">Nguồn: ${escape(figure.sources.join(' · '))}</p>
    </body></html>`;
    // Use a local page URL so local SVGs can load under the file origin.
    const temp = path.join(root, 'hinh/pdf', '.' + figure.id + '.html');
    await fs.writeFile(temp, sheet);
    await page.goto(pathToFileURL(temp).href, { waitUntil: 'load' });
    await page.evaluate(() => document.fonts.ready);
    await page.pdf({ path: path.join(root, 'hinh/pdf', figure.id + '.pdf'), preferCSSPageSize: true, printBackground: true });
    await fs.unlink(temp);
    manifest.push({ ...figure, figure_number: index + 1, svg_width: width, svg_height: height, pdf_paper: paper, portrait });
    console.log('PNG/PDF', figure.id, `${Math.round(width)}×${Math.round(height)}`, paper, portrait ? 'portrait' : 'landscape');
  }
} finally {
  await browser.close();
}
await fs.writeFile(path.join(root, 'danh-muc-hinh.json'), JSON.stringify(manifest, null, 2) + '\n');

const links = config.figures.map((f, i) => `<li><a href="#${f.id}">Hình ${i + 1}. ${escape(f.title)}</a></li>`).join('');
const cards = config.figures.map((f, i) => `<article id="${f.id}"><h2>Hình ${i + 1}. ${escape(f.title)}</h2><p class="meta">${escape(f.type)} · Đặt tại: ${escape(f.section)}</p><figure><a href="hinh/svg/${f.id}.svg"><img loading="lazy" src="hinh/svg/${f.id}.svg" alt="${escape(f.title)}"></a><figcaption>${escape(f.caption)}</figcaption></figure><p>${escape(f.description)}</p><p class="downloads"><a href="hinh/svg/${f.id}.svg">SVG vector</a> · <a href="hinh/png/${f.id}.png">PNG</a> · <a href="hinh/pdf/${f.id}.pdf">PDF</a> · <a href="nguon/${f.id}.${['01-ca-su-dung','03-hoat-dong-phan-tich'].includes(f.id) ? 'puml' : 'mmd'}">Nguồn chỉnh sửa</a></p><p class="meta">Đối chiếu: ${f.sources.map(s => { const [file, line] = s.split(':'); return `<a href="../../${file}#L${line}">${escape(s)}</a>`; }).join(' · ')}</p></article>`).join('');
const rows = (items) => items.map(row => `<tr>${row.map(c => `<td>${escape(c)}</td>`).join('')}</tr>`).join('');
const html = `<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escape(config.title)}</title><style>
  body{max-width:1380px;margin:32px auto;padding:0 24px;background:#f1f5f9;color:#172033;font:17px/1.65 "DejaVu Sans",Arial,sans-serif}
  header,article,section{background:#fff;padding:28px 34px;margin-bottom:26px;border:1px solid #cbd5e1;border-radius:8px}
  h1{font-size:28px;line-height:1.35}h2{font-size:23px;line-height:1.4}a{color:#1e40af}figure{margin:22px 0}figure img{display:block;max-width:100%;height:auto;max-height:1700px;margin:auto}figcaption{margin-top:18px;font-style:italic}.meta{color:#475569;font-size:14px}
  table{border-collapse:collapse;width:100%;font-size:15px}td,th{padding:10px 12px;border:1px solid #cbd5e1;text-align:left;vertical-align:top}th{background:#eff6ff}nav ol{columns:2;column-gap:36px}nav li{break-inside:avoid;margin:5px 0}li{margin:8px 0}code{background:#f1f5f9;padding:2px 4px}
  @media(max-width:800px){body{padding:0 10px}header,article,section{padding:16px}nav ol{columns:1}table{font-size:12px}td,th{padding:6px}}
</style></head><body><header><h1>${escape(config.title)}</h1><p>${escape(config.scope)}</p><p><a href="So-do-Crop-Map.pdf">Tải bộ PDF</a> · <a href="So-do-Crop-Map.docx">Tải Word</a> · <a href="README.md">Đọc thuyết minh và quy ước tên</a></p><nav><ol>${links}</ol></nav></header>${cards}<section><h2>Quy ước tên gọi</h2><table><thead><tr><th>Thuật ngữ</th><th>Nghĩa dùng trong báo cáo</th></tr></thead><tbody>${rows(config.terms)}</tbody></table></section><section><h2>Đối chiếu API</h2><table><thead><tr><th>Method</th><th>Endpoint</th><th>Ý nghĩa</th><th>HTTP status chính</th></tr></thead><tbody>${rows(config.api)}</tbody></table></section><section><h2>Quy tắc cần giữ khi diễn giải</h2><ol>${config.rules.map(r => `<li>${escape(r)}</li>`).join('')}</ol></section></body></html>`;
await fs.writeFile(path.join(root, 'index.html'), html);
console.log('Preview: docs/bao-cao/index.html');
