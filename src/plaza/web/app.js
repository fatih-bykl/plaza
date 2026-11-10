"use strict";
/* Plaza Ofis — kuşbakışı ofis arayüzü */

const SVGNS = "http://www.w3.org/2000/svg";
const $ = (s) => document.querySelector(s);

const ODA_G = 340, ODA_Y = 236, ARA = 14, KORIDOR = 66, KENAR = 26, SUTUN = 3;
const RENKLER = ["#4c6ef5", "#12b886", "#f59f00", "#e64980", "#7950f2", "#15aabf", "#fd7e14", "#82c91e"];
const CEO_RENK = "#343a40";
const TENLER = ["#f1c7a3", "#e0a77f", "#c68863", "#8d5a3b", "#f6d5b8"];
const SACLAR = ["#2b2118", "#5a3a22", "#a0672e", "#d8b45c", "#1b1b1b", "#7a4a3a", "#b9b9b9"];
const DURUM_IKON = { dusunuyor: "💭", calisiyor: "⌨️", bitti: "✅", hata: "⚠️", bekliyor: "⏳" };
const DURUM_YAZI = {
  bosta: "Boşta", dusunuyor: "Düşünüyor", calisiyor: "Çalışıyor", bitti: "Görevi bitirdi", hata: "Hata", bekliyor: "Bekliyor",
};

const durum = {
  ofis: null,          // /api/ofis yanıtı
  masalar: {},         // key -> masa bilgisi (+renk)
  konum: {},           // key -> {x,y} (svg)
  masaDurum: {},       // key -> durum
  masaAciklama: {},    // key -> son açıklama
  secili: null,
  seciliDep: null,
  adimlar: [],         // {calisan, gorev, tur, durum, cikti}
  plan: "",
  sonuc: null,         // {sonuc, klasor, dosyalar}
  calisiyor: false,
  kuyruk: [],          // sıradaki görevler
  ekler: [],           // {ad, icerik}
  devamIs: null,       // {id, talep}
  onay: null,          // onay bekleyen plan {ozet, adimlar}
  isOzet: null,        // tamamlanan işin istatistiği
  istatistik: null,    // tüm zamanlar, masa bazında
  talep: "",
};

/* ---------------------------------------------------------------- yardımcılar */
function el(ad, nit = {}, ebeveyn) {
  const e = document.createElementNS(SVGNS, ad);
  for (const [k, v] of Object.entries(nit)) e.setAttribute(k, v);
  if (ebeveyn) ebeveyn.appendChild(e);
  return e;
}
function hash(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h; }
function kacis(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function saat(t) { return new Date(t * 1000).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
function modelKisa(id) {
  const m = durum.ofis?.modeller.find((x) => x.id === id);
  return m ? m.kisa : id.split("/").pop();
}
async function api(yol, secenek = {}) {
  const r = await fetch(yol, { headers: { "Content-Type": "application/json" }, ...secenek });
  if (!r.ok) {
    let mesaj = r.statusText;
    try { mesaj = (await r.json()).detail || mesaj; } catch { /* metin değil */ }
    throw new Error(typeof mesaj === "string" ? mesaj : JSON.stringify(mesaj));
  }
  return r.headers.get("content-type")?.includes("json") ? r.json() : r.text();
}

/* Basit ve güvenli Markdown → HTML */
function md(metin) {
  const satirlar = kacis(metin || "").split("\n");
  let html = "", liste = null, kod = false, paragraf = [];
  const satirIci = (s) => s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])[_*]([^_*]+)[_*](?=[\s).,!?:;]|$)/g, "$1<em>$2</em>");
  const paragrafBitir = () => { if (paragraf.length) { html += `<p>${satirIci(paragraf.join(" "))}</p>`; paragraf = []; } };
  const listeBitir = () => { if (liste) { html += `</${liste}>`; liste = null; } };
  for (const s of satirlar) {
    if (s.trim().startsWith("```")) {
      paragrafBitir(); listeBitir();
      html += kod ? "</code></pre>" : "<pre><code>"; kod = !kod; continue;
    }
    if (kod) { html += s + "\n"; continue; }
    const b = s.match(/^(#{1,4})\s+(.*)/);
    const ul = s.match(/^\s*[-*]\s+(.*)/);
    const ol = s.match(/^\s*\d+[.)]\s+(.*)/);
    if (b) { paragrafBitir(); listeBitir(); html += `<h${b[1].length}>${satirIci(b[2])}</h${b[1].length}>`; }
    else if (ul || ol) {
      paragrafBitir();
      const tur = ul ? "ul" : "ol";
      if (liste !== tur) { listeBitir(); html += `<${tur}>`; liste = tur; }
      html += `<li>${satirIci((ul || ol)[1])}</li>`;
    } else if (!s.trim()) { paragrafBitir(); listeBitir(); }
    else { listeBitir(); paragraf.push(s); }
  }
  paragrafBitir(); listeBitir(); if (kod) html += "</code></pre>";
  return html;
}

/* ---------------------------------------------------------------- ofis çizimi */
function ofisiCiz() {
  const svg = $("#ofis");
  svg.replaceChildren();
  const o = durum.ofis;
  durum.masalar = { ceo: { ...o.ceo, renk: CEO_RENK } };
  o.departmanlar.forEach((d, i) => d.staff.forEach((s) => (durum.masalar[s.key] = { ...s, renk: RENKLER[i % RENKLER.length] })));

  // Hücre yerleşimi: ilk satırın ortası CEO
  const deps = o.departmanlar.map((d, i) => ({ tur: "dep", dep: d, renk: RENKLER[i % RENKLER.length] }));
  const hucreler = [deps[0] || { tur: "bos" }, { tur: "ceo" }, deps[1] || { tur: "bos" }];
  for (const d of deps.slice(2)) hucreler.push(d);
  while (hucreler.length % SUTUN) hucreler.push({ tur: "bos" });
  const ilkBos = hucreler.findIndex((h) => h.tur === "bos");
  if (ilkBos >= 0) hucreler[ilkBos] = { tur: "yeni" };
  const satir = hucreler.length / SUTUN;

  const G = KENAR * 2 + SUTUN * ODA_G + (SUTUN - 1) * ARA;
  const Y = KENAR * 2 + satir * ODA_Y + Math.max(1, satir - 1) * KORIDOR + (satir === 1 ? KORIDOR : 0);
  svg.setAttribute("viewBox", `0 0 ${G} ${Y}`);

  const defs = el("defs", {}, svg);
  const fayans = el("pattern", { id: "fayans", width: 26, height: 26, patternUnits: "userSpaceOnUse" }, defs);
  el("path", { d: "M26 0H0V26", fill: "none", stroke: "currentColor", "stroke-width": 0.6, opacity: 0.18 }, fayans);
  const parke = el("pattern", { id: "parke", width: 60, height: 16, patternUnits: "userSpaceOnUse" }, defs);
  el("rect", { width: 60, height: 16, class: "ahsap", "stroke-width": 0, opacity: 0.32 }, parke);
  el("path", { d: "M0 16H60M30 0V8M0 8H60M12 8V16M48 8V16", fill: "none", stroke: "var(--ahsap-koyu)", "stroke-width": 0.8, opacity: 0.35 }, parke);
  const bulanik = el("filter", { id: "parilti", x: "-50%", y: "-50%", width: "200%", height: "200%" }, defs);
  el("feGaussianBlur", { stdDeviation: 4 }, bulanik);
  const golge = el("filter", { id: "golge", x: "-20%", y: "-20%", width: "140%", height: "140%" }, defs);
  el("feDropShadow", { dx: 0, dy: 1.5, stdDeviation: 1.5, "flood-opacity": 0.25 }, golge);

  svg.style.color = "var(--metin)";
  el("rect", { x: 0, y: 0, width: G, height: Y, rx: 10, class: "koridor" }, svg);
  el("rect", { x: 3, y: 3, width: G - 6, height: Y - 6, rx: 8, class: "duvar", "stroke-width": 6 }, svg);
  // Koridor halısı
  for (let r = 0; r < Math.max(1, satir - 1); r++) {
    const ky = KENAR + (r + 1) * ODA_Y + r * KORIDOR;
    el("rect", { x: KENAR + 30, y: ky + KORIDOR / 2 - 9, width: G - 2 * KENAR - 60, height: 18, rx: 9, fill: "var(--vurgu)", opacity: 0.08 }, svg);
  }

  durum.konum = {};
  hucreler.forEach((h, i) => {
    const sat = Math.floor(i / SUTUN), sut = i % SUTUN;
    const x = KENAR + sut * (ODA_G + ARA), y = KENAR + sat * (ODA_Y + KORIDOR);
    odaCiz(svg, h, x, y, sat === 0 ? "alt" : "ust");
  });
  ucanKatman = el("g", {}, svg);
  durumlariUygula();
}

let ucanKatman = null;

function odaCiz(svg, h, x, y, kapiYonu) {
  const g = el("g", { transform: `translate(${x} ${y})` }, svg);
  const W = ODA_G, H = ODA_Y;
  if (h.tur === "yeni") {
    const y = el("g", { class: "yeni-oda", tabindex: 0, role: "button", "aria-label": "Yeni departman ekle" }, g);
    el("rect", { x: 4, y: 4, width: W - 8, height: H - 8, rx: 10 }, y);
    el("text", { x: W / 2, y: H / 2 - 6 }, y).textContent = "+";
    el("text", { x: W / 2, y: H / 2 + 18 }, y).textContent = "Yeni departman";
    y.addEventListener("click", departmanEkle);
    y.addEventListener("keydown", (e) => { if (e.key === "Enter") departmanEkle(); });
    return;
  }
  // zemin
  const zemin = el("rect", { width: W, height: H, fill: "var(--yuzey)" }, g);
  if (h.tur === "dep") {
    zemin.classList.add("oda-zemin");
    zemin.addEventListener("click", () => departmanSec(h.dep.key));
  }
  if (h.tur === "ceo") el("rect", { width: W, height: H, fill: "url(#parke)" }, g);
  else {
    el("rect", { width: W, height: H, fill: h.renk || "var(--soluk)", opacity: h.tur === "bos" ? 0.05 : 0.1, "pointer-events": "none" }, g);
    el("rect", { width: W, height: H, fill: "url(#fayans)", "pointer-events": "none" }, g);
  }
  // duvarlar (kapı boşluklu)
  const kapi = 54, kx = W / 2 - kapi / 2;
  const yol = kapiYonu === "alt"
    ? `M0 0H${W}V${H}H${kx + kapi}M${kx} ${H}H0V0`
    : `M${kx} 0H0V${H}H${W}V0H${kx + kapi}`;
  el("path", { d: yol, class: "duvar" }, g);
  const ky = kapiYonu === "alt" ? H : 0, yon = kapiYonu === "alt" ? -1 : 1;
  el("path", { d: `M${kx} ${ky} L${kx} ${ky + yon * kapi} A${kapi} ${kapi} 0 0 ${yon > 0 ? 0 : 1} ${kx + kapi} ${ky}`, class: "kapi-yay" }, g);

  // etiket
  const baslik = h.tur === "ceo" ? "CEO Odası" : h.tur === "dep" ? h.dep.name : "Toplantı Odası";
  const ey = kapiYonu === "alt" ? 12 : H - 34;
  const et = el("g", { transform: `translate(12 ${ey})` }, g);
  const yaziGen = baslik.length * 7.3 + 22;
  el("rect", { width: yaziGen, height: 22, rx: 6, class: "oda-etiket-arka", filter: "url(#golge)" }, et);
  if (h.tur !== "bos") el("circle", { cx: 11, cy: 11, r: 4.5, fill: h.tur === "ceo" ? CEO_RENK : h.renk }, et);
  const t = el("text", { x: h.tur === "bos" ? 10 : 20, y: 15.5, class: "oda-etiket" }, et);
  t.textContent = baslik;
  if (h.tur === "dep") {
    et.classList.add("oda-zemin");
    et.addEventListener("click", () => departmanSec(h.dep.key));
    if (h.dep.staff.length < durum.ofis.max_masa) {
      const arti = el("g", { class: "oda-arti", transform: `translate(${yaziGen + 14} 11)`, tabindex: 0, role: "button", "aria-label": `${baslik}: masa ekle` }, et);
      el("circle", { r: 10 }, arti);
      el("text", { y: 0.5 }, arti).textContent = "+";
      const ac = (e) => { e.stopPropagation(); departmanSec(h.dep.key, true); };
      arti.addEventListener("click", ac);
      arti.addEventListener("keydown", (e) => { if (e.key === "Enter") ac(e); });
    }
  }

  // dekor
  const bitkiY = kapiYonu === "alt" ? 26 : H - 26;
  bitki(g, W - 24, bitkiY);
  if (h.tur === "ceo") {
    bitki(g, 24, kapiYonu === "alt" ? H - 26 : 26);
    // kitaplık
    const ky2 = kapiYonu === "alt" ? 6 : H - 18;
    el("rect", { x: W - 150, y: ky2, width: 100, height: 12, class: "ahsap" }, g);
    for (let i = 0; i < 9; i++) el("rect", { x: W - 146 + i * 10.5, y: ky2 + 2, width: 7, height: 8, fill: RENKLER[i % RENKLER.length], opacity: 0.75 }, g);
    // koltuk takımı
    const kty = kapiYonu === "alt" ? H - 50 : 46;
    el("rect", { x: W - 92, y: kty - 16, width: 64, height: 32, rx: 8, fill: "#6c757d", opacity: 0.85 }, g);
    el("rect", { x: W - 86, y: kty - 10, width: 52, height: 20, rx: 5, fill: "#adb5bd", opacity: 0.7 }, g);
  }
  if (h.tur === "bos") {
    el("ellipse", { cx: W / 2, cy: H / 2, rx: 78, ry: 36, class: "ahsap" }, g);
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2;
      el("circle", { cx: W / 2 + Math.cos(a) * 100, cy: H / 2 + Math.sin(a) * 54, r: 11, class: "sandalye", opacity: 0.8 }, g);
    }
    return;
  }

  // masalar
  const kisiler = h.tur === "ceo" ? [durum.masalar.ceo] : h.dep.staff.map((s) => durum.masalar[s.key]);
  const n = kisiler.length;
  if (!n) {
    el("text", { x: W / 2, y: H / 2, class: "bos-oda-yazi" }, g).textContent = "Henüz masa yok — eklemek için + düğmesine basın";
    return;
  }
  const sut = n <= 2 ? n : n <= 4 ? 2 : 3;
  const sat = Math.ceil(n / sut);
  const ust = kapiYonu === "alt" ? 38 : 10, alt = kapiYonu === "alt" ? 10 : 38;
  const hucreY = (H - ust - alt) / sat;
  const olcek = Math.min(h.tur === "ceo" ? 1.4 : 1.3, (W / sut - 16) / 130, hucreY / 138);
  kisiler.forEach((k, i) => {
    const r = Math.floor(i / sut), c = i % sut;
    const buSatir = Math.min(sut, n - r * sut);
    const mx = (W / buSatir) * (c + 0.5);
    const my = ust + hucreY * (r + 0.5) - 4 * olcek;
    masaCiz(g, k, mx, my, olcek, h.tur === "ceo", sut > 1 ? 15 : 22);
    durum.konum[k.key] = { x: x0(g) + mx, y: y0(g) + my };
  });
}
function x0(g) { return +g.getAttribute("transform").match(/translate\(([-\d.]+)/)[1]; }
function y0(g) { return +g.getAttribute("transform").match(/translate\([-\d.]+ ([-\d.]+)/)[1]; }

function bitki(g, x, y) {
  const b = el("g", { transform: `translate(${x} ${y})` }, g);
  el("circle", { r: 11, class: "saksi" }, b);
  for (let i = 0; i < 6; i++) {
    const a = (i / 6) * Math.PI * 2;
    el("ellipse", { cx: Math.cos(a) * 8, cy: Math.sin(a) * 8, rx: 8, ry: 5, transform: `rotate(${(a * 180) / Math.PI} ${Math.cos(a) * 8} ${Math.sin(a) * 8})`, class: i % 2 ? "bitki" : "bitki-koyu" }, b);
  }
  el("circle", { r: 5, class: "bitki" }, b);
}

function masaCiz(g, k, x, y, olcek, ceo, rolSiniri = 22) {
  const h = hash(k.key);
  const ten = TENLER[h % TENLER.length], sac = SACLAR[(h >> 3) % SACLAR.length];
  const m = el("g", {
    class: "masa", transform: `translate(${x} ${y}) scale(${olcek})`, tabindex: 0, role: "button",
    "data-key": k.key, "aria-label": `${k.isim}, ${k.role}`,
  }, g);
  el("rect", { x: -70, y: -60, width: 140, height: 140, class: "secim" }, m);
  if (ceo) el("ellipse", { cx: 0, cy: 6, rx: 96, ry: 56, fill: "#a61e4d", opacity: 0.12 }, m);

  const dg = ceo ? 70 : 55; // masa yarı genişliği
  el("rect", { x: -dg, y: -30, width: dg * 2, height: 40, rx: 4, class: "ahsap", filter: "url(#golge)" }, m);
  if (ceo) el("rect", { x: dg - 22, y: 10, width: 22, height: 34, rx: 3, class: "ahsap" }, m); // L kolu
  el("rect", { x: -28, y: -38, width: 56, height: 16, rx: 5, class: "ekran-isik", filter: "url(#parilti)" }, m);
  el("rect", { x: -23, y: -28, width: 46, height: 6, rx: 2, class: "ekran" }, m);
  el("rect", { x: -6, y: -22, width: 12, height: 5, rx: 1, class: "ekran", opacity: 0.7 }, m);
  el("rect", { x: -16, y: -12, width: 32, height: 8, rx: 1.5, class: "klavye" }, m);
  el("ellipse", { cx: 25, cy: -8, rx: 3, ry: 4.5, class: "klavye" }, m);
  el("circle", { cx: -dg + 14, cy: -16, r: 5, fill: "#fff", stroke: "#adb5bd" }, m);
  el("circle", { cx: -dg + 14, cy: -16, r: 3.2, fill: "#6f4e37" }, m);
  el("rect", { x: dg - 26, y: -26, width: 15, height: 19, fill: "#fff", stroke: "#ced4da", transform: `rotate(10 ${dg - 18} -16)` }, m);
  if (ceo) el("rect", { x: -dg + 26, y: -26, width: 12, height: 18, rx: 1, fill: "#495057", opacity: 0.7 }, m); // telefon

  // sandalye + kişi
  el("circle", { cx: 0, cy: 22, r: ceo ? 17 : 15, class: "sandalye" }, m);
  el("rect", { x: ceo ? -16 : -14, y: 31, width: ceo ? 32 : 28, height: 8, rx: 4, class: "sandalye" }, m);
  const gomlek = k.renk;
  const kolSol = el("g", { class: "kol-sol" }, m);
  el("rect", { x: -16, y: -2, width: 7, height: 18, rx: 3.5, fill: gomlek }, kolSol);
  el("circle", { cx: -12.5, cy: -2, r: 3.6, fill: ten }, kolSol);
  const kolSag = el("g", { class: "kol-sag" }, m);
  el("rect", { x: 9, y: -2, width: 7, height: 18, rx: 3.5, fill: gomlek }, kolSag);
  el("circle", { cx: 12.5, cy: -2, r: 3.6, fill: ten }, kolSag);
  el("ellipse", { cx: 0, cy: 20, rx: 17, ry: 9, fill: gomlek }, m);
  if (ceo) el("path", { d: "M-3 12 L0 24 L3 12 Z", fill: "#c92a2a" }, m); // kravat ucu
  const kafa = el("g", { class: "kafa" }, m);
  el("circle", { cx: -9, cy: 16, r: 2.4, fill: ten }, kafa);
  el("circle", { cx: 9, cy: 16, r: 2.4, fill: ten }, kafa);
  el("circle", { cx: 0, cy: 16, r: 9, fill: sac }, kafa);

  // durum balonu
  const balon = el("g", { class: "balon", transform: "translate(46 -46)" }, m);
  el("path", { d: "M-6 12 L-14 22 L2 13 Z", fill: "var(--yuzey)", stroke: "var(--cizgi)" }, balon);
  el("rect", { x: -17, y: -13, width: 34, height: 26, rx: 11, filter: "url(#golge)" }, balon);
  el("text", { x: 0, y: 1, class: "balon-yazi" }, balon);

  const isim = el("text", { x: 0, y: 58, class: "isim-etiket" }, m);
  isim.textContent = ceo ? `${k.isim} · CEO` : k.isim;
  const model = el("text", { x: 0, y: 71, class: "model-etiket" }, m);
  model.textContent = `${k.role.length > rolSiniri ? k.role.slice(0, rolSiniri - 1) + "…" : k.role} · ${modelKisa(k.model)}`;

  m.addEventListener("click", () => masaSec(k.key));
  m.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); masaSec(k.key); } });
}

function durumlariUygula() {
  document.querySelectorAll(".masa").forEach((m) => {
    const key = m.dataset.key;
    const d = durum.masaDurum[key] || "bosta";
    m.classList.remove("bosta", "dusunuyor", "calisiyor", "bitti", "hata", "bekliyor");
    m.classList.add(d);
    m.classList.toggle("secili", durum.secili === key);
    m.classList.toggle("pasif", key !== "ceo" && durum.masalar[key] && !durum.masalar[key].aktif);
    const t = m.querySelector(".balon-yazi");
    if (t) t.textContent = DURUM_IKON[d] || "";
  });
}

function kagitUcur(kimden, kime) {
  const a = durum.konum[kimden], b = durum.konum[kime];
  if (!a || !b || !ucanKatman) return;
  const g = el("g", { class: "ucan-kagit" }, ucanKatman);
  el("rect", { x: -7, y: -9, width: 14, height: 18, rx: 1.5, filter: "url(#golge)" }, g);
  for (let i = 0; i < 3; i++) el("line", { x1: -4, x2: 4, y1: -4 + i * 4, y2: -4 + i * 4 }, g);
  const kx = (a.x + b.x) / 2, ky = Math.min(a.y, b.y) - 110;
  const sure = 1100, bas = performance.now();
  const adim = (t) => {
    const p = Math.min(1, (t - bas) / sure), e = p < 0.5 ? 2 * p * p : 1 - (-2 * p + 2) ** 2 / 2;
    const x = (1 - e) ** 2 * a.x + 2 * (1 - e) * e * kx + e * e * b.x;
    const y = (1 - e) ** 2 * a.y + 2 * (1 - e) * e * ky + e * e * b.y;
    g.setAttribute("transform", `translate(${x} ${y}) rotate(${Math.sin(p * Math.PI * 2) * 18}) scale(${1 + Math.sin(p * Math.PI) * 0.5})`);
    if (p < 1) requestAnimationFrame(adim); else g.remove();
  };
  requestAnimationFrame(adim);
}

/* ---------------------------------------------------------------- panel */
function gorunum(ad) {
  for (const g of ["gorev", "masa", "departman"]) $(`#gorunum-${g}`).classList.toggle("gizli", ad !== g);
}

function ofisGuncelle(yeni) {
  durum.ofis = yeni;
  ofisiCiz();
  if (durum.secili && !durum.masalar[durum.secili]) { durum.secili = null; gorunum("gorev"); }
  if (durum.seciliDep && !durum.ofis.departmanlar.some((d) => d.key === durum.seciliDep)) { durum.seciliDep = null; gorunum("gorev"); }
  if (durum.secili) masaPaneliDoldur();
  if (durum.seciliDep) departmanPaneliDoldur();
  adimlariCiz();
}

async function islem(fn) {
  try { ofisGuncelle(await fn()); return true; } catch (err) { alert(err.message); return false; }
}

async function departmanEkle() {
  const ad = prompt("Yeni departmanın adı:", "Pazarlama Departmanı");
  if (!ad?.trim()) return;
  const onceki = new Set(durum.ofis.departmanlar.map((d) => d.key));
  if (await islem(() => api("/api/departman", { method: "POST", body: JSON.stringify({ name: ad.trim() }) }))) {
    const yeni = durum.ofis.departmanlar.find((d) => !onceki.has(d.key));
    if (yeni) departmanSec(yeni.key, true);
  }
}

function departmanSec(dkey, masaEkle = false) {
  durum.secili = null;
  durum.seciliDep = dkey;
  durumlariUygula();
  departmanPaneliDoldur();
  gorunum("departman");
  if (masaEkle) $("#yeni-masa-form").role.focus();
}

function departmanPaneliDoldur() {
  const i = durum.ofis.departmanlar.findIndex((d) => d.key === durum.seciliDep);
  if (i < 0) return;
  const d = durum.ofis.departmanlar[i];
  $("#dep-renk").style.background = RENKLER[i % RENKLER.length];
  $("#dep-baslik").textContent = d.name;
  $("#dep-form").name.value = d.name;
  const ul = $("#dep-masalar");
  ul.replaceChildren();
  if (!d.staff.length) ul.innerHTML = `<li class="aciklama" style="cursor:default">Bu odada masa yok.</li>`;
  for (const s of d.staff) {
    const li = document.createElement("li");
    li.innerHTML = `<b>${kacis(s.isim)}</b> <span class="aciklama">${kacis(s.role)} · ${kacis(modelKisa(s.model))}${s.aktif ? "" : " · pasif"}</span>`;
    li.onclick = () => masaSec(s.key);
    ul.appendChild(li);
  }
  const f = $("#yeni-masa-form");
  if (!f.model.options.length) f.model.replaceChildren(...durum.ofis.modeller.map((m) => new Option(m.ad, m.id)));
  const dolu = d.staff.length >= durum.ofis.max_masa;
  f.querySelector("button[type=submit]").disabled = dolu;
  $("#dep-dolu").classList.toggle("gizli", !dolu);
  $("#dep-dolu").textContent = `Oda dolu (en fazla ${durum.ofis.max_masa} masa)`;
}

$("#dep-form").addEventListener("submit", (e) => {
  e.preventDefault();
  islem(() => api(`/api/departman/${durum.seciliDep}`, { method: "PUT", body: JSON.stringify({ name: e.target.name.value.trim() }) }));
});

$("#yeni-masa-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const veri = { isim: f.isim.value.trim(), role: f.role.value.trim(), goal: f.goal.value.trim(), model: f.model.value };
  if (await islem(() => api(`/api/departman/${durum.seciliDep}/masa`, { method: "POST", body: JSON.stringify(veri) }))) {
    f.isim.value = ""; f.role.value = ""; f.goal.value = "";
  }
});

$("#dep-kaldir").addEventListener("click", () => {
  const d = durum.ofis.departmanlar.find((x) => x.key === durum.seciliDep);
  if (!d || !confirm(`"${d.name}" departmanı ve içindeki ${d.staff.length} masa kaldırılsın mı?`)) return;
  islem(() => api(`/api/departman/${d.key}`, { method: "DELETE" }));
});

$("#departman-ekle").addEventListener("click", departmanEkle);
$("#ofis-sifirla").addEventListener("click", () => {
  if (!confirm("Tüm masa ayarları, eklenen departman/masalar ve kaldırılanlar sıfırlanacak. Emin misiniz?")) return;
  islem(() => api("/api/ofis/sifirla", { method: "POST" }));
});

function masaSec(key) {
  durum.secili = key;
  durum.seciliDep = null;
  durumlariUygula();
  masaPaneliDoldur();
  gorunum("masa");
}

function masaPaneliDoldur() {
  const k = durum.masalar[durum.secili];
  if (!k) return;
  const ceo = k.key === "ceo";
  $("#masa-renk").style.background = k.renk;
  $("#masa-isim").textContent = k.isim;
  $("#masa-alt").textContent = `${k.role} · ${k.department}`;
  const d = durum.masaDurum[k.key] || "bosta";
  $("#masa-durum").textContent = `${DURUM_IKON[d] || "•"} ${DURUM_YAZI[d]}${durum.masaAciklama[k.key] ? " — " + durum.masaAciklama[k.key] : ""}`;
  const ist = durum.istatistik?.masalar?.[k.key];
  $("#masa-istatistik").textContent = ist
    ? `Tüm zamanlar: ${ist.gorev} ${ceo ? "iş" : "görev"} · ${sayiKisa(ist.token)} token · ort. ${sureYaz(ist.sure / ist.gorev)}`
    : "Tüm zamanlar: henüz gerçek bir görev yok (simülasyonlar sayılmaz).";

  const f = $("#masa-form");
  f.isim.value = k.isim; f.role.value = k.role; f.goal.value = k.goal; f.backstory.value = k.backstory;
  const sec = f.model_secim;
  sec.replaceChildren(...durum.ofis.modeller.map((m) => new Option(m.ad, m.id)), new Option("Özel model…", "__ozel"));
  const hazir = durum.ofis.modeller.some((m) => m.id === k.model);
  sec.value = hazir ? k.model : "__ozel";
  f.model_ozel.value = hazir ? "" : k.model;
  $("#ozel-model-kap").classList.toggle("gizli", hazir);

  $("#arac-kap").classList.toggle("gizli", ceo);
  $("#aktif-kap").classList.toggle("gizli", ceo);
  f.aktif.checked = !!k.aktif;
  $("#araclar").replaceChildren(...durum.ofis.araclar.map((a) => {
    const l = document.createElement("label");
    l.innerHTML = `<input type="checkbox" value="${kacis(a)}" ${k.tools?.includes(a) ? "checked" : ""}> ${kacis(a)}`;
    return l;
  }));
  $("#sifirla").disabled = !k.ozel;
  $("#masa-kaldir").classList.toggle("gizli", ceo);
  $("#kaydedildi").classList.add("gizli");

  // Bu masanın görevleri
  const ul = $("#masa-gorevler");
  ul.replaceChildren();
  const liste = ceo
    ? [durum.plan && { baslik: "Plan", metin: durum.plan }, durum.sonuc && { baslik: "Nihai teslimat", metin: durum.sonuc.sonuc }].filter(Boolean)
    : durum.adimlar.filter((a) => a.calisan === k.key).map((a) => ({
      baslik: `${a.tur ? "Revizyon " + a.tur : "Görev"} · ${DURUM_YAZI[a.durum] || a.durum}`, metin: a.gorev, cikti: a.cikti,
    }));
  if (!liste.length) ul.innerHTML = `<li class="aciklama" style="cursor:default">Bu işte henüz görevi yok.</li>`;
  for (const x of liste) {
    const li = document.createElement("li");
    li.innerHTML = `<b>${kacis(x.baslik)}</b><div class="aciklama" style="margin:2px 0 0">${kacis(x.metin.slice(0, 160))}</div>`;
    li.onclick = () => modalAc(`${k.isim} — ${x.baslik}`, x.cikti ? `**Görev:** ${x.metin}\n\n---\n\n${x.cikti}` : x.metin);
    ul.appendChild(li);
  }
}

$("#masa-form").model_secim.addEventListener("change", (e) => {
  $("#ozel-model-kap").classList.toggle("gizli", e.target.value !== "__ozel");
});

$("#masa-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, key = durum.secili;
  const model = f.model_secim.value === "__ozel" ? f.model_ozel.value.trim() : f.model_secim.value;
  const veri = { isim: f.isim.value.trim(), model, role: f.role.value.trim(), goal: f.goal.value, backstory: f.backstory.value };
  if (key !== "ceo") {
    veri.aktif = f.aktif.checked;
    veri.tools = [...$("#araclar").querySelectorAll("input:checked")].map((i) => i.value);
  }
  try {
    ofisGuncelle(await api(`/api/masa/${key}`, { method: "PUT", body: JSON.stringify(veri) }));
    $("#kaydedildi").classList.remove("gizli");
  } catch (err) { alert(err.message); }
});

$("#sifirla").addEventListener("click", async () => {
  if (!confirm("Bu masanın ayarları YAML'daki varsayılanlara dönsün mü?")) return;
  islem(() => api(`/api/masa/${durum.secili}`, { method: "DELETE" }));
});

$("#masa-kaldir").addEventListener("click", () => {
  const k = durum.masalar[durum.secili];
  if (!k || !confirm(`${k.isim} (${k.role}) masası kaldırılsın mı?`)) return;
  islem(() => api(`/api/calisan/${k.key}`, { method: "DELETE" }));
});

document.querySelectorAll(".geri-btn").forEach((b) => b.addEventListener("click", () => {
  durum.secili = null; durum.seciliDep = null; durumlariUygula(); gorunum("gorev");
}));

function sayiKisa(n) { return n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k" : String(n); }
function sureYaz(s) { return s >= 60 ? `${Math.floor(s / 60)} dk ${Math.round(s % 60)} sn` : `${Math.round(s)} sn`; }
function metrik(a) {
  if (a.sure == null) return "";
  return `⏱ ${sureYaz(a.sure)}${a.token ? " · " + sayiKisa(a.token) + " token" : ""}`;
}

function adimlariCiz() {
  $("#plan-ozet").textContent = durum.plan || (durum.calisiyor ? "CEO plan hazırlıyor…" : "Henüz görev yok.");
  const ol = $("#adimlar");
  ol.replaceChildren();
  // tur + aşama gruplarına göre başlık ekle
  const grupBoyu = {};
  for (const a of durum.adimlar) { const g = `${a.tur}-${a.asama || 1}`; grupBoyu[g] = (grupBoyu[g] || 0) + 1; }
  const asamaVar = new Set(durum.adimlar.filter((a) => !a.tur).map((a) => a.asama || 1)).size > 1;
  let onceki = null;
  for (const a of durum.adimlar) {
    const g = `${a.tur}-${a.asama || 1}`;
    if (g !== onceki && (asamaVar || a.tur || grupBoyu[g] > 1)) {
      const h = document.createElement("li");
      h.className = "asama-baslik";
      h.textContent = a.tur
        ? `Revizyon turu ${a.tur}${grupBoyu[g] > 1 ? " · paralel" : ""}`
        : `Aşama ${a.asama || 1}${grupBoyu[g] > 1 ? " · " + grupBoyu[g] + " görev paralel" : ""}`;
      ol.appendChild(h);
    }
    onceki = g;
    const k = durum.masalar[a.calisan] || { isim: a.calisan, role: "" };
    const li = document.createElement("li");
    li.className = `${a.durum} ${a.tur ? "revizyon" : ""}`;
    const ikon = { bekliyor: "○", calisiyor: "⌨️", bitti: "✅", hata: "⚠️" }[a.durum] || "○";
    const m = metrik(a);
    li.innerHTML = `<span class="ikon">${ikon}</span><div><b>${kacis(k.isim)}</b> <span class="aciklama">${kacis(k.role)}</span><div class="gorev">${kacis(a.gorev)}</div>${m ? `<div class="metrik">${m}</div>` : ""}</div>`;
    li.onclick = () => (a.cikti ? modalAc(`${k.isim} — ${k.role}`, `**Görev:** ${a.gorev}\n\n---\n\n${a.cikti}`) : masaSec(a.calisan));
    li.title = a.cikti ? "Çıktıyı görmek için tıklayın" : "Masayı açmak için tıklayın";
    ol.appendChild(li);
  }
  const oz = $("#is-ozet");
  oz.classList.toggle("gizli", !durum.isOzet);
  if (durum.isOzet) {
    const i = durum.isOzet;
    oz.textContent = `Toplam ${sureYaz(i.sure || 0)}` +
      (i.toplam_token ? ` · ${sayiKisa(i.toplam_token)} token (CEO ${sayiKisa(i.ceo_token || 0)})` : "");
  }
}

/* ---------------------------------------------------------------- plan onayı */
function onayCiz() {
  const kap = $("#plan-duzenle");
  kap.classList.toggle("gizli", !durum.onay);
  if (!durum.onay) return;
  $("#onay-ozet").textContent = durum.onay.ozet;
  const liste = $("#onay-adimlar");
  liste.replaceChildren();
  const calisanlar = durum.ofis.departmanlar.flatMap((d) => d.staff.filter((s) => s.aktif));
  durum.onay.adimlar.forEach((a, i) => {
    const d = document.createElement("div");
    d.className = "onay-satir";
    const asama = document.createElement("input");
    Object.assign(asama, { type: "number", min: 1, max: 9, value: a.asama || 1, title: "Aşama (aynı aşama = paralel)" });
    asama.oninput = () => (a.asama = Math.max(1, +asama.value || 1));
    const sec = document.createElement("select");
    sec.replaceChildren(...calisanlar.map((s) => new Option(`${s.isim} — ${s.role}`, s.key)));
    sec.value = a.calisan;
    sec.onchange = () => (a.calisan = sec.value);
    const sil = document.createElement("button");
    Object.assign(sil, { className: "sil", textContent: "✕", title: "Adımı sil" });
    sil.onclick = () => { durum.onay.adimlar.splice(i, 1); onayCiz(); };
    const gorev = document.createElement("textarea");
    gorev.rows = 2; gorev.value = a.gorev;
    gorev.oninput = () => (a.gorev = gorev.value);
    d.append(asama, sec, sil, gorev);
    liste.appendChild(d);
  });
}
$("#onay-adim-ekle").addEventListener("click", () => {
  const ilk = durum.ofis.departmanlar.flatMap((d) => d.staff.filter((s) => s.aktif))[0];
  if (!ilk || !durum.onay) return;
  const son = Math.max(1, ...durum.onay.adimlar.map((a) => a.asama || 1));
  durum.onay.adimlar.push({ calisan: ilk.key, gorev: "", asama: son });
  onayCiz();
  $("#onay-adimlar").lastElementChild?.querySelector("textarea")?.focus();
});
$("#onay-gonder").addEventListener("click", async () => {
  try {
    await api("/api/plan/onay", { method: "POST", body: JSON.stringify({ adimlar: durum.onay.adimlar }) });
  } catch (err) { alert(err.message); }
});

/* ---------------------------------------------------------------- kuyruk */
function kuyrukCiz() {
  $("#kuyruk-kap").classList.toggle("gizli", !durum.kuyruk.length);
  const ul = $("#kuyruk");
  ul.replaceChildren();
  durum.kuyruk.forEach((k, i) => {
    const li = document.createElement("li");
    li.innerHTML = `<b>${i + 1}.</b><span title="${kacis(k.talep)}">${kacis(k.talep)}${k.simulasyon ? " (sim.)" : ""}</span>`;
    const b = document.createElement("button");
    b.textContent = "Çıkar";
    b.onclick = () => api(`/api/kuyruk/${k.id}`, { method: "DELETE" });
    li.appendChild(b);
    ul.appendChild(li);
  });
}

function kaydet(t, metin) {
  const li = document.createElement("li");
  li.innerHTML = `<time>${saat(t)}</time><span>${kacis(metin)}</span>`;
  $("#kayit").prepend(li);
}

function rozet(metin, sinif = "") {
  const r = $("#durum-rozeti");
  r.textContent = metin; r.className = `rozet ${sinif}`;
  document.title = metin === "Hazır" ? "Plaza Ofis" : `${metin} · Plaza Ofis`;
}

function calisiyorAyarla(v) {
  durum.calisiyor = v;
  $("#gonder").textContent = v ? "Sıraya ekle" : "CEO'ya gönder";
  $("#durdur").classList.toggle("gizli", !v);
}

function bildir(baslik, govde) {
  try {
    if (document.hidden && "Notification" in window && Notification.permission === "granted") new Notification(baslik, { body: govde });
  } catch { /* bildirim desteklenmiyor */ }
}

/* ---------------------------------------------------------------- olaylar */
function olay(o) {
  const canli = !o.tekrar;
  const isim = (k) => durum.masalar[k]?.isim || k;
  switch (o.tip) {
    case "kuyruk":
      durum.kuyruk = o.liste;
      kuyrukCiz();
      return;
    case "is_basladi":
      durum.masaDurum = {}; durum.masaAciklama = {}; durum.adimlar = []; durum.plan = ""; durum.sonuc = null;
      durum.isOzet = null; durum.onay = null; durum.talep = o.talep;
      $("#kayit").replaceChildren(); $("#hata").classList.add("gizli"); $("#sonuc-gor").classList.add("gizli");
      calisiyorAyarla(true); rozet(o.simulasyon ? "Çalışıyor (simülasyon)" : "Çalışıyor", "calisiyor");
      kaydet(o.zaman, `Yeni talep CEO'ya geldi: ${o.talep}`);
      if (o.onceki_is) kaydet(o.zaman, `Önceki işin devamı: ${o.onceki_is}`);
      if (o.ekler?.length) kaydet(o.zaman, `Ek dosyalar: ${o.ekler.join(", ")}`);
      break;
    case "durum":
      durum.masaDurum[o.masa] = o.durum;
      durum.masaAciklama[o.masa] = o.aciklama || "";
      if (o.masa === "ceo" && o.aciklama) kaydet(o.zaman, `${isim("ceo")}: ${o.aciklama}`);
      break;
    case "plan_onay_bekleniyor":
      durum.onay = { ozet: o.ozet, adimlar: o.adimlar.map((a) => ({ ...a })) };
      rozet("Plan onayınızı bekliyor", "calisiyor");
      kaydet(o.zaman, "CEO'nun planı onayınızı bekliyor");
      onayCiz();
      if (canli) { gorunum("gorev"); $("#plan-duzenle").scrollIntoView({ behavior: "smooth" }); bildir("Plaza: plan onayı", o.ozet); }
      break;
    case "plan":
      if (durum.onay) { durum.onay = null; onayCiz(); rozet("Çalışıyor", "calisiyor"); }
      durum.plan = o.ozet;
      durum.adimlar = o.adimlar.map((a) => ({ ...a, tur: 0, durum: "bekliyor", cikti: null }));
      kaydet(o.zaman, `CEO planı hazır: ${o.adimlar.length} adım, ${new Set(o.adimlar.map((a) => a.asama)).size} aşama`);
      break;
    case "gorev_atandi": {
      let a = durum.adimlar.find((x) => x.calisan === o.kime && x.tur === o.tur && x.durum === "bekliyor");
      if (!a) { a = { calisan: o.kime, gorev: o.gorev, tur: o.tur, asama: o.asama }; durum.adimlar.push(a); }
      a.durum = "calisiyor"; a.gorev = o.gorev;
      kaydet(o.zaman, `CEO → ${isim(o.kime)}: görev verildi`);
      if (canli) kagitUcur(o.kimden, o.kime);
      break;
    }
    case "gorev_bitti": {
      const a = durum.adimlar.find((x) => x.calisan === o.kime && x.tur === o.tur && x.durum === "calisiyor");
      if (a) { a.durum = "bitti"; a.cikti = o.cikti; a.sure = o.sure; a.token = o.token; }
      kaydet(o.zaman, `${isim(o.kime)} → CEO: çıktı teslim edildi${o.sure != null ? " (" + sureYaz(o.sure) + ")" : ""}`);
      if (canli) kagitUcur(o.kime, "ceo");
      break;
    }
    case "degerlendirme":
      if (o.onay) kaydet(o.zaman, "CEO çıktıları onayladı");
      else {
        kaydet(o.zaman, `CEO revizyon istedi (tur ${o.tur}): ${o.revizyonlar.map((r) => isim(r.calisan)).join(", ")}`);
        for (const r of o.revizyonlar) durum.adimlar.push({ ...r, tur: o.tur, durum: "bekliyor", cikti: null });
      }
      break;
    case "is_bitti":
      durum.sonuc = { sonuc: o.sonuc, klasor: o.klasor, dosyalar: o.dosyalar };
      durum.isOzet = o.istatistik || null;
      calisiyorAyarla(false); rozet("Tamamlandı", "bitti");
      $("#sonuc-gor").classList.remove("gizli");
      kaydet(o.zaman, `İş tamamlandı → cikti/${o.klasor}`);
      if (canli) {
        bildir("Plaza: iş tamamlandı", durum.talep || "");
        if (!durum.kuyruk.length) sonucuGoster();
        gecmisiYukle(); istatistikYukle();
      }
      break;
    case "is_hatasi":
      durum.onay = null; onayCiz();
      calisiyorAyarla(false); rozet("Hata", "hata");
      $("#hata").textContent = o.mesaj; $("#hata").classList.remove("gizli");
      for (const [k, d] of Object.entries(durum.masaDurum)) if (["dusunuyor", "calisiyor", "bekliyor"].includes(d)) durum.masaDurum[k] = "hata";
      kaydet(o.zaman, `HATA: ${o.mesaj}`);
      if (canli) { bildir("Plaza: hata", o.mesaj); gecmisiYukle(); }
      break;
    case "is_durduruldu":
      durum.onay = null; onayCiz();
      calisiyorAyarla(false); rozet("Durduruldu");
      for (const [k, d] of Object.entries(durum.masaDurum)) if (d !== "bitti") durum.masaDurum[k] = "bosta";
      for (const a of durum.adimlar) if (a.durum === "calisiyor") a.durum = "hata";
      kaydet(o.zaman, "İş kullanıcı tarafından durduruldu");
      if (canli) gecmisiYukle();
      break;
  }
  durumlariUygula();
  adimlariCiz();
  if (durum.secili) masaPaneliDoldur();
}

function olaylariDinle() {
  const es = new EventSource("/api/olaylar");
  es.onmessage = (e) => olay(JSON.parse(e.data));
}

/* ---------------------------------------------------------------- modal & geçmiş */
function modalAc(baslik, metin, dosyalar = null, klasor = null, talep = null) {
  $("#modal-baslik").textContent = baslik;
  $("#modal-icerik").innerHTML = md(metin);
  const kap = $("#modal-dosyalar");
  kap.replaceChildren();
  $("#modal-eylemler").classList.toggle("gizli", !klasor);
  if (klasor) {
    $("#modal-zip").href = `/api/is/${encodeURIComponent(klasor)}/zip`;
    $("#modal-devam").onclick = () => devamAyarla(klasor, talep || baslik);
  }
  if (dosyalar && klasor) {
    for (const d of dosyalar.filter((x) => x !== "is.json")) {
      const b = document.createElement("button");
      b.textContent = d;
      if (d === "SONUC.md") b.classList.add("secili");
      b.onclick = async () => {
        kap.querySelectorAll("button").forEach((x) => x.classList.toggle("secili", x === b));
        try {
          const t = await api(`/api/dosya?yol=${encodeURIComponent(klasor + "/" + d)}`);
          $("#modal-icerik").innerHTML = d.endsWith(".md") ? md(t) : `<pre><code>${kacis(t)}</code></pre>`;
        } catch (err) { $("#modal-icerik").textContent = err.message; }
      };
      kap.appendChild(b);
    }
  }
  $("#modal").classList.remove("gizli");
}
const modalKapat = () => $("#modal").classList.add("gizli");
$("#modal-kapat").onclick = modalKapat;
$("#modal").onclick = (e) => { if (e.target.id === "modal") modalKapat(); };
document.addEventListener("keydown", (e) => { if (e.key === "Escape") modalKapat(); });

function sonucuGoster() {
  const s = durum.sonuc;
  if (s) modalAc("Nihai teslimat", s.sonuc || "", s.dosyalar, s.klasor, durum.talep);
}
$("#sonuc-gor").onclick = sonucuGoster;

function devamAyarla(klasor, talep) {
  durum.devamIs = klasor ? { id: klasor, talep } : null;
  $("#devam-cip").classList.toggle("gizli", !klasor);
  if (klasor) {
    $("#devam-yazi").textContent = `↪ Devam: ${talep.slice(0, 60)}`;
    modalKapat(); durum.secili = null; durum.seciliDep = null; durumlariUygula(); gorunum("gorev");
    $("#talep").focus();
  }
}
$("#devam-iptal").onclick = () => devamAyarla(null);

async function gecmisiYukle() {
  const liste = await api("/api/gecmis");
  const ul = $("#gecmis");
  ul.replaceChildren();
  if (!liste.length) ul.innerHTML = `<li class="aciklama" style="cursor:default">Henüz iş yok.</li>`;
  const etiket = { is_bitti: "tamamlandı", is_hatasi: "hata", is_durduruldu: "durduruldu" };
  for (const j of liste) {
    const li = document.createElement("li");
    li.innerHTML = `${kacis(j.talep.slice(0, 90))}<small>${kacis(j.id)} · ${etiket[j.durum] || j.durum}${j.simulasyon ? " · simülasyon" : ""}</small>`;
    li.onclick = async () => {
      const d = await api(`/api/is/${j.id}`);
      const bitti = d.olaylar.find((o) => o.tip === "is_bitti");
      const hata = d.olaylar.find((o) => o.tip === "is_hatasi");
      modalAc(j.talep.slice(0, 70), bitti ? bitti.sonuc : hata ? `**Hata:** ${hata.mesaj}` : "_Sonuç yok._", d.dosyalar, j.id, j.talep);
    };
    ul.appendChild(li);
  }
}

async function istatistikYukle() {
  try { durum.istatistik = await api("/api/istatistik"); } catch { durum.istatistik = null; }
  if (durum.secili) masaPaneliDoldur();
}

/* ---------------------------------------------------------------- ek dosyalar */
function eklerCiz() {
  const kap = $("#ekler");
  kap.replaceChildren();
  durum.ekler.forEach((e, i) => {
    const s = document.createElement("span");
    s.textContent = `${e.ad} (${sayiKisa(e.icerik.length)} kr.)`;
    const b = document.createElement("button");
    Object.assign(b, { textContent: "✕", title: "Kaldır" });
    b.onclick = () => { durum.ekler.splice(i, 1); eklerCiz(); };
    s.appendChild(b);
    kap.appendChild(s);
  });
}
$("#ek-dosya").addEventListener("change", async (e) => {
  for (const f of e.target.files) {
    if (durum.ekler.length >= 10) { alert("En fazla 10 dosya eklenebilir."); break; }
    const metin = await f.text();
    if (metin.includes("\u0000")) { alert(`${f.name}: yalnızca metin dosyaları eklenebilir.`); continue; }
    if (metin.length > 200000) { alert(`${f.name}: dosya çok büyük (en fazla 200.000 karakter).`); continue; }
    durum.ekler = durum.ekler.filter((x) => x.ad !== f.name);
    durum.ekler.push({ ad: f.name, icerik: metin });
  }
  e.target.value = "";
  eklerCiz();
});

/* ---------------------------------------------------------------- görev gönderme */
$("#gonder").addEventListener("click", async () => {
  const talep = $("#talep").value.trim();
  if (!talep) { $("#talep").focus(); return; }
  $("#hata").classList.add("gizli");
  try {
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
  } catch { /* yok say */ }
  try {
    const r = await api("/api/gorev", {
      method: "POST",
      body: JSON.stringify({
        talep, simulasyon: $("#simulasyon").checked, max_revizyon: +$("#revizyon").value,
        plan_onayi: $("#plan-onayi").checked, onceki_is: durum.devamIs?.id || null, ekler: durum.ekler,
      }),
    });
    if (r.kuyrukta) kaydet(Date.now() / 1000, `Görev sıraya alındı (${r.sira}. sırada): ${talep}`);
    $("#talep").value = ""; durum.ekler = []; eklerCiz(); devamAyarla(null);
  } catch (err) {
    $("#hata").textContent = err.message; $("#hata").classList.remove("gizli");
  }
});
$("#talep").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("#gonder").click(); });
$("#durdur").addEventListener("click", async () => {
  await api("/api/durdur", { method: "POST" });
  rozet("Durduruluyor… (mevcut adım bitince)");
});

/* ---------------------------------------------------------------- tema */
function temaUygula(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
}
try { temaUygula(localStorage.getItem("plaza-tema")); } catch { /* depolama yok */ }
$("#tema").addEventListener("click", () => {
  const koyu = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const yeni = koyu ? "light" : "dark";
  temaUygula(yeni);
  try { localStorage.setItem("plaza-tema", yeni); } catch { /* depolama yok */ }
});

/* ---------------------------------------------------------------- başlat */
(async function baslat() {
  durum.ofis = await api("/api/ofis");
  if (!durum.ofis.api_anahtari) {
    $("#simulasyon").checked = true;
    $("#anahtar-uyari").classList.remove("gizli");
  }
  ofisiCiz();
  adimlariCiz();
  gecmisiYukle();
  istatistikYukle();
  olaylariDinle();
})();
