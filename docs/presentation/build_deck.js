// Builds TriLock_Final_Review.pptx.
//   NODE_PATH=<dir with node_modules for pptxgenjs, react-icons, sharp> node build_deck.js
// Numbers come from deck_data.json (export_deck_data.py reads them from the stored evaluation runs).
// Screenshots come from ../screenshots (made by frontend/e2e/smoke.mjs against the real app).
const pptxgen = require('pptxgenjs');
const React = require('react');
const RDS = require('react-dom/server');
const sharp = require('sharp');
const fi = require('react-icons/fi');
const md = require('react-icons/md');
const fs = require('fs');
const path = require('path');

const SKILL = process.env.SKILL_DIR;
const { applyTheme } = require(path.join(SKILL, 'scripts/apply_theme.js'));
const D = JSON.parse(fs.readFileSync(path.join(__dirname, 'deck_data.json'), 'utf8'));
const SHOTS = path.join(__dirname, '..', 'screenshots');
const OUT = path.join(__dirname, 'TriLock_Final_Review.pptx');
const TESTS = process.env.TESTS || '262';

// ---------------------------------------------------------------- theme
const THEME = {
  name: 'TriLock',
  headFontFace: 'Cambria',
  bodyFontFace: 'Calibri',
  colors: {
    dk1: '0B1320', lt1: 'FFFFFF', dk2: '15253D', lt2: 'EEF2F7',
    accent1: '3F86F5', accent2: 'E5A23C', accent3: '2FA97C', accent4: 'E4606B', accent5: '8EA0B6', accent6: '8FBAFF',
    hlink: '3F86F5', folHlink: '8EA0B6',
  },
};
const HEX = THEME.colors;

const pres = new pptxgen();
pres.layout = 'LAYOUT_16x9'; // 10 x 5.625 in
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = 'TriLock: Risk-Adaptive Multimodal Biometric Authentication for Digital Banking';
pres.subject = 'Final year project review';
const C = pres.SchemeColor;

// ---------------------------------------------------------------- layouts
pres.defineSlideMaster({
  title: 'TITLE_DARK',
  background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: 'title', type: 'title', x: 0.6, y: 1.35, w: 5.4, h: 1.0, fontSize: 60, bold: true, color: C.background1, margin: 0, valign: 'top', align: 'left' }, text: '' } },
    { placeholder: { options: { name: 'body', type: 'body', x: 0.6, y: 2.5, w: 5.0, h: 1.0, fontSize: 20, color: C.accent6, margin: 0, valign: 'top', align: 'left', bullet: false }, text: '' } },
  ],
});
pres.defineSlideMaster({
  title: 'CONTENT',
  background: { color: C.background2 },
  objects: [
    { placeholder: { options: { name: 'title', type: 'title', x: 0.6, y: 0.32, w: 8.8, h: 0.75, fontSize: 28, bold: true, color: C.text1, margin: 0, valign: 'top', align: 'left' }, text: '' } },
    { text: { text: 'TriLock  |  Final year project review', options: { x: 0.6, y: 5.3, w: 5, h: 0.22, fontSize: 10, color: C.accent5, margin: 0 } } },
  ],
  slideNumber: { x: 9.0, y: 5.3, w: 0.4, h: 0.22, fontSize: 10, color: C.accent5, align: 'right', margin: 0 },
});
pres.defineSlideMaster({
  title: 'CLOSING_DARK',
  background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: 'title', type: 'title', x: 0.6, y: 0.95, w: 5, h: 0.6, fontSize: 32, bold: true, color: C.background1, margin: 0, valign: 'top', align: 'left' }, text: '' } },
  ],
});

// ---------------------------------------------------------------- helpers
const tb = (s, text, o = {}) => s.addText(text, { isTextBox: true, margin: 0, ...o });
const shadow = () => ({ type: 'outer', color: '0B1320', opacity: 0.1, blur: 8, offset: 2, angle: 90 });
const card = (s, x, y, w, h, o = {}) =>
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: C.background1 }, line: { color: 'D8E0EB', width: 0.75 }, shadow: shadow(), ...o });
const arrow = (s, x, y, w, h, o = {}) =>
  s.addShape(pres.ShapeType.line, { x, y, w, h, line: { color: C.accent5, width: 1.5, endArrowType: 'triangle' }, ...o });

const iconCache = {};
async function icon(Comp, hex, size = 256) {
  const key = (Comp.displayName || Comp.name) + hex;
  if (iconCache[key]) return iconCache[key];
  const svg = RDS.renderToStaticMarkup(React.createElement(Comp, { color: '#' + hex, size: String(size) }));
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  return (iconCache[key] = 'image/png;base64,' + png.toString('base64'));
}
// icon inside a soft tinted circle
async function iconBadge(s, Comp, x, y, d, name, hex = HEX.accent1, tint = C.accent1) {
  s.addShape(pres.ShapeType.ellipse, { x, y, w: d, h: d, fill: { color: tint, transparency: 86 }, line: { color: tint, width: 0, transparency: 100 }, objectName: `${name} circle` });
  const pad = d * 0.26;
  s.addImage({ data: await icon(Comp, hex), x: x + pad, y: y + pad, w: d - 2 * pad, h: d - 2 * pad, altText: name, objectName: name });
}
const pc = (x, d = 2) => `${(x * 100).toFixed(d)}%`;
const ci = (c) => `${(c[0] * 100).toFixed(1)} to ${(c[1] * 100).toFixed(1)}`;

// a cropped screenshot with a bold caption and one line of detail underneath
async function cropFrame(s, name, x, y, w, head, detail, slotH) {
  const file = path.join(__dirname, 'crops', name + '.png');
  const meta = await sharp(file).metadata();
  const h = (w * meta.height) / meta.width;
  s.addShape(pres.ShapeType.roundRect, { x: x - 0.04, y: y - 0.04, w: w + 0.08, h: h + 0.08, rectRadius: 0.05, fill: { color: C.background1 }, line: { color: 'D8E0EB', width: 0.75 }, shadow: shadow() });
  s.addImage({ path: file, x, y, w, h, altText: head, objectName: `Screenshot: ${head}` });
  const cy = y + (slotH || h) + 0.2;
  tb(s, head, { x: x - 0.04, y: cy, w: w + 0.08, h: 0.3, fontSize: 14, bold: true, color: C.text1 });
  tb(s, detail, { x: x - 0.04, y: cy + 0.32, w: w + 0.08, h: 0.6, fontSize: 12, color: C.text2, valign: 'top' });
  return h;
}

function shotFrame(s, file, x, y, w, caption) {
  const h = (w * 900) / 1360;
  s.addShape(pres.ShapeType.roundRect, { x: x - 0.04, y: y - 0.04, w: w + 0.08, h: h + 0.08, rectRadius: 0.05, fill: { color: C.background1 }, line: { color: 'D8E0EB', width: 0.75 }, shadow: shadow() });
  s.addImage({ path: path.join(SHOTS, file), x, y, w, h, altText: caption, objectName: `Screenshot: ${caption}` });
  if (caption) tb(s, caption, { x: x - 0.04, y: y + h + 0.14, w: w + 0.08, h: 0.5, fontSize: 12, color: C.text2, valign: 'top' });
  return h;
}

const content = (title, section) => {
  const s = pres.addSlide({ masterName: 'CONTENT', sectionTitle: section });
  s.addText(title, { placeholder: 'title' });
  return s;
};

// ---------------------------------------------------------------- build
async function build() {
  // section 1: opening --------------------------------------------------
  pres.addSection({ title: 'Opening' });
  {
    const s = pres.addSlide({ masterName: 'TITLE_DARK', sectionTitle: 'Opening' });
    tb(s, 'FINAL YEAR PROJECT REVIEW', { x: 0.6, y: 0.65, w: 5, h: 0.3, fontSize: 12, bold: true, color: C.accent5, charSpacing: 4 });
    s.addText('TriLock', { placeholder: 'title' });
    s.addText('Risk-adaptive multimodal biometric authentication for digital banking', { placeholder: 'body' });
    tb(s, 'Face  |  Voice  |  Fingerprint', { x: 0.6, y: 4.55, w: 5, h: 0.3, fontSize: 14, color: C.accent5 });
    tb(s, 'Academic prototype. All transactions are simulated.', { x: 0.6, y: 4.9, w: 5.5, h: 0.3, fontSize: 12, color: C.accent5 });
    // motif: three traits around a lock
    const cx = 7.65, cy = 2.75;
    const sats = [[cx, cy - 1.6, fi.FiCamera, 'Face'], [cx + 1.45, cy + 1.05, fi.FiMic, 'Voice'], [cx - 1.45, cy + 1.05, md.MdFingerprint, 'Fingerprint']];
    for (const [x, y] of sats) s.addShape(pres.ShapeType.line, { x: Math.min(cx, x), y: Math.min(cy, y), w: Math.abs(x - cx) || 0.001, h: Math.abs(y - cy) || 0.001, flipH: x < cx && y > cy ? true : false, line: { color: C.accent5, width: 1, dashType: 'dash' } });
    s.addShape(pres.ShapeType.ellipse, { x: cx - 0.85, y: cy - 0.85, w: 1.7, h: 1.7, fill: { color: C.text2 }, line: { color: C.accent1, width: 2 } });
    s.addImage({ data: await icon(fi.FiLock, HEX.accent6), x: cx - 0.4, y: cy - 0.4, w: 0.8, h: 0.8, altText: 'Lock' });
    for (const [x, y, Comp, label] of sats) {
      s.addShape(pres.ShapeType.ellipse, { x: x - 0.4, y: y - 0.4, w: 0.8, h: 0.8, fill: { color: C.text2 }, line: { color: C.accent1, width: 1.25 } });
      s.addImage({ data: await icon(Comp, HEX.accent6), x: x - 0.22, y: y - 0.22, w: 0.44, h: 0.44, altText: label });
      const ly = label === 'Face' ? y - 0.72 : y + 0.46;      // the top label goes above so the line does not cross it
      tb(s, label === 'Fingerprint' ? 'Fingerprint (optional)' : label, { x: x - 0.9, y: ly, w: 1.8, h: 0.25, fontSize: 12, color: C.accent5, align: 'center' });
    }
    s.addNotes(
      "Good morning ma'am. My project is TriLock. It is a biometric authentication system for digital banking, where the amount of proof we ask for depends on how risky the payment is.\n\n" +
      "Before I start, one thing I want to be clear about: this is an academic prototype. All the transactions are simulated, there is no real money and no real bank behind it. What I want to show you today is how the system makes its decisions, how I tested it, and honestly where it is still weak."
    );
  }

  // section 2: problem and idea -----------------------------------------
  pres.addSection({ title: 'Problem and idea' });
  {
    const s = content('Passwords alone do not prove who you are', 'Problem and idea');
    const rows = [
      [fi.FiKey, 'Credentials can be taken', 'Passwords and one-time codes can be guessed, phished or shared. Whoever has them is "you".'],
      [fi.FiCamera, 'One biometric is not enough', 'A single trait can be faked with a photo or a recording, or fail in bad light and noise.'],
      [fi.FiSliders, 'Every payment gets the same check', 'A coffee and a large transfer are treated alike, so the check is either too weak or too annoying.'],
    ];
    let y = 1.3;
    for (const [Comp, head, body] of rows) {
      await iconBadge(s, Comp, 0.6, y, 0.62, head);
      tb(s, head, { x: 1.42, y: y - 0.02, w: 4.4, h: 0.3, fontSize: 16, bold: true, color: C.text1 });
      tb(s, body, { x: 1.42, y: y + 0.3, w: 4.4, h: 0.8, fontSize: 14, color: C.text2, valign: 'top' });
      y += 1.27;
    }
    s.addShape(pres.ShapeType.roundRect, { x: 6.1, y: 1.3, w: 3.3, h: 3.5, rectRadius: 0.1, fill: { color: C.text2 }, line: { color: C.text2, width: 0 } });
    tb(s, 'The question', { x: 6.4, y: 1.6, w: 2.7, h: 0.3, fontSize: 12, bold: true, color: C.accent6, charSpacing: 2 });
    tb(s, 'How do we verify a person strongly, without making every small payment painful?', { x: 6.4, y: 2.0, w: 2.7, h: 2.5, fontSize: 21, italic: true, color: C.background1, fontFace: THEME.headFontFace, valign: 'top' });
    s.addNotes(
      "The starting point is simple. A password only proves that someone knows a secret, not that they are the person. Passwords and OTPs can be guessed, phished or shared.\n\n" +
      "Biometrics help, but one biometric on its own can also fail. A photo can fool a face check, a recording can fool a voice check, and honest users get rejected in poor light or a noisy room.\n\n" +
      "The third problem is what made me choose this topic. Most systems apply the same check to every payment. So the check is either too weak for a big transfer or too annoying for a small one. That is the question on the right: how do we verify strongly without making small payments painful?"
    );
  }
  {
    const s = content('The idea: match the check to the risk', 'Problem and idea');
    const steps = [
      ['Low', 'One biometric is enough', C.accent3, 1.05],
      ['Medium', 'Two biometrics', C.accent1, 1.6],
      ['High', 'Face and voice, live', C.accent2, 2.15],
      ['Critical', 'Face and voice, live, higher bar', C.accent4, 2.7],
    ];
    const baseY = 4.0;
    steps.forEach(([label, text, col, h], i) => {
      const x = 0.6 + i * 2.25;
      s.addShape(pres.ShapeType.roundRect, { x, y: baseY - h, w: 2.05, h, rectRadius: 0.06, fill: { color: col }, line: { color: col, width: 0 }, objectName: `${label} bar` });
      tb(s, label, { x: x + 0.15, y: baseY - h + 0.12, w: 1.8, h: 0.35, fontSize: 18, bold: true, color: C.background1, fontFace: THEME.headFontFace });
      tb(s, text, { x: x + 0.15, y: baseY - h + 0.5, w: 1.8, h: 0.7, fontSize: 14, color: C.background1, valign: 'top' });
    });
    const notes = ['Small payments stay smooth', 'Large payments get more proof', 'Missing evidence is never a match'];
    notes.forEach((t, i) => tb(s, t, { x: 0.6 + i * 3.0, y: 4.35, w: 2.8, h: 0.5, fontSize: 14, bold: true, color: C.text1 }));
    tb(s, 'More risk, more evidence', { x: 0.6, y: 1.3, w: 3.6, h: 0.35, fontSize: 18, italic: true, color: C.text2, fontFace: THEME.headFontFace });
    s.addNotes(
      "So the idea behind TriLock is to match the strictness of the check to the risk of the payment.\n\n" +
      "For a low-risk payment, one biometric is enough. As the risk goes up, the system asks for more evidence: two biometrics, then face and voice together, and for the highest risk, a higher bar on top of that.\n\n" +
      "There is one rule I kept everywhere. If a sample is missing, or the camera fails, or the model crashes, the system never treats that as a match. It is just treated as no evidence."
    );
  }
  {
    const s = content('TriLock in one view', 'Problem and idea');
    const boxes = [
      [fi.FiLock, 'Sign in', 'Password, then live face and voice'],
      [fi.FiSend, 'Payment', 'Amount, recipient, device'],
      [fi.FiTrendingUp, 'Risk score', '0 to 100, rule based'],
      [fi.FiUsers, 'Evidence', 'Face, voice, fingerprint'],
      [fi.FiCheckCircle, 'Decision', 'Approve, reject or ask for more'],
    ];
    const w = 1.58, gap = 0.225;
    for (let i = 0; i < boxes.length; i++) {
      const x = 0.6 + i * (w + gap);
      card(s, x, 1.35, w, 1.75);
      await iconBadge(s, boxes[i][0], x + w / 2 - 0.27, 1.5, 0.54, boxes[i][1]);
      tb(s, boxes[i][1], { x: x + 0.08, y: 2.1, w: w - 0.16, h: 0.3, fontSize: 15, bold: true, color: C.text1, align: 'center' });
      tb(s, boxes[i][2], { x: x + 0.1, y: 2.42, w: w - 0.2, h: 0.62, fontSize: 12, color: C.text2, align: 'center', valign: 'top' });
      if (i < boxes.length - 1) arrow(s, x + w + 0.03, 2.2, gap - 0.06, 0);
    }
    const pillars = [['Multimodal', 'Three traits that fail in different ways, so they cover each other.'], ['Risk-adaptive', 'The bar rises with the risk of the payment.'], ['Liveness-aware', 'High-risk steps need a live head turn and spoken words.']];
    pillars.forEach(([h, t], i) => {
      const x = 0.6 + i * 3.0;
      tb(s, h, { x, y: 3.55, w: 2.8, h: 0.3, fontSize: 16, bold: true, color: C.accent1 });
      tb(s, t, { x, y: 3.9, w: 2.75, h: 0.9, fontSize: 14, color: C.text2, valign: 'top' });
    });
    s.addNotes(
      "This is the whole system on one slide. The user signs in with a password and then a live face and voice check. When they start a payment, the system scores how risky it is. Then it collects whatever biometric evidence the user gives, combines it, and returns one of three outcomes: approved, rejected, or additional verification required.\n\n" +
      "Three ideas hold it together. It is multimodal, so the traits cover each other's weaknesses. It is risk-adaptive, so the bar rises with the payment. And it checks liveness for the high-risk steps, so a still photo or a recording is not enough."
    );
  }

  // section 3: design -----------------------------------------------------
  pres.addSection({ title: 'Design' });
  {
    const s = content('System architecture', 'Design');
    const cols = [
      [fi.FiMonitor, 'Browser', 'React + Vite', ['Camera and microphone', 'Dashboard and analytics', 'Makes no decisions']],
      [fi.FiServer, 'API', 'FastAPI', ['Routes, validation', 'Sessions, access control', 'One error format']],
      [fi.FiLayers, 'Services', 'Python', ['Risk engine', 'Fusion and policy', 'Sign-in and liveness']],
      [fi.FiCpu, 'Biometrics', '3 modules', ['Face: YuNet, SFace', 'Voice: ECAPA-TDNN', 'Finger: SIFT, RANSAC']],
    ];
    const w = 2.0, gap = 0.267;
    for (let i = 0; i < cols.length; i++) {
      const x = 0.6 + i * (w + gap);
      card(s, x, 1.25, w, 2.45);
      await iconBadge(s, cols[i][0], x + 0.15, 1.38, 0.5, cols[i][1]);
      tb(s, cols[i][1], { x: x + 0.75, y: 1.38, w: w - 0.8, h: 0.28, fontSize: 15, bold: true, color: C.text1 });
      tb(s, cols[i][2], { x: x + 0.75, y: 1.68, w: w - 0.8, h: 0.22, fontSize: 11, color: C.accent5 });
      tb(s, cols[i][3].map((t, k) => ({ text: t, options: { bullet: true, breakLine: k < 2 } })), { x: x + 0.15, y: 2.15, w: w - 0.3, h: 1.45, fontSize: 12, color: C.text2, valign: 'top', paraSpaceAfter: 4 });
      if (i < cols.length - 1) arrow(s, x + w + 0.02, 2.4, gap - 0.04, 0);
    }
    const store = [[fi.FiDatabase, 'SQLite', 'users, payments, attempts, audit log'], [fi.FiShield, 'Templates', 'encrypted numbers, never photos'], [fi.FiClipboard, 'Evaluation', 'offline scripts, reproducible']];
    for (let i = 0; i < store.length; i++) {
      const x = 0.6 + i * 3.0;
      card(s, x, 4.0, 2.8, 0.95, { fill: { color: C.background1 } });
      await iconBadge(s, store[i][0], x + 0.15, 4.2, 0.55, store[i][1], HEX.accent3, C.accent3);
      tb(s, store[i][1], { x: x + 0.85, y: 4.13, w: 1.85, h: 0.28, fontSize: 14, bold: true, color: C.text1 });
      tb(s, store[i][2], { x: x + 0.85, y: 4.43, w: 1.85, h: 0.42, fontSize: 11, color: C.text2, valign: 'top' });
    }
    s.addNotes(
      "On the architecture: the browser is a React app that captures the camera and microphone and shows the pages. It makes no decisions. Everything important happens on the server.\n\n" +
      "The FastAPI backend handles routes, validation, sessions and access control. Behind it are the services: the risk engine, the fusion and decision policy, and the sign-in and liveness logic. Each biometric is its own module with the same interface, so I could test and evaluate them separately.\n\n" +
      "At the bottom is storage. SQLite for users, payments and every authentication attempt. The biometric templates are stored as encrypted numbers, never as photos or recordings. The evaluation scripts run offline and save their results in the same database, which is what the analytics page reads."
    );
  }
  {
    const s = content('Why face, voice and fingerprint', 'Design');
    const cards = [
      [fi.FiCamera, 'Face', 'Required', C.accent3, 'Every laptop and phone has a camera. It is quick, natural and needs no extra hardware.'],
      [fi.FiMic, 'Voice', 'Required', C.accent3, 'Works remotely with only a microphone, and carries different information than the face.'],
      [md.MdFingerprint, 'Fingerprint', 'Optional', C.accent5, 'A strong trait, but a browser cannot read a sensor. We work on images, so it is a future enhancement.'],
    ];
    for (let i = 0; i < 3; i++) {
      const x = 0.6 + i * 3.0, w = 2.8;
      card(s, x, 1.3, w, 3.0);
      await iconBadge(s, cards[i][0], x + 0.25, 1.5, 0.7, cards[i][1], i === 2 ? HEX.accent5 : HEX.accent1, i === 2 ? C.accent5 : C.accent1);
      tb(s, cards[i][1], { x: x + 1.05, y: 1.55, w: 1.7, h: 0.35, fontSize: 18, bold: true, color: C.text1, fontFace: THEME.headFontFace });
      s.addShape(pres.ShapeType.roundRect, { x: x + 1.1, y: 1.98, w: 0.95, h: 0.26, rectRadius: 0.13, fill: { color: cards[i][3], transparency: 80 }, line: { color: cards[i][3], width: 0, transparency: 100 } });
      tb(s, cards[i][2], { x: x + 1.1, y: 1.98, w: 0.95, h: 0.26, fontSize: 11, bold: true, color: i === 2 ? C.text2 : C.text1, align: 'center', valign: 'middle' });
      tb(s, cards[i][4], { x: x + 0.25, y: 2.7, w: w - 0.5, h: 1.45, fontSize: 14, color: C.text2, valign: 'top' });
    }
    tb(s, 'Different traits fail in different ways, so combining them covers each other\'s weak spots.', { x: 0.6, y: 4.5, w: 8.8, h: 0.5, fontSize: 16, italic: true, color: C.text1, fontFace: THEME.headFontFace });
    s.addNotes(
      "I chose these three because each one has a clear reason. Face is easy: every device has a camera. Voice works remotely with just a microphone, and it gives different information from the face, so one can cover the other.\n\n" +
      "Fingerprint is the honest one. A normal browser cannot read a fingerprint sensor, so I could only work with fingerprint images, and I could not find a real fingerprint dataset to test on. That is why it is marked optional and is a future enhancement. The system is built so that nothing requires it. Face and voice are the core.\n\n" +
      "The reason for combining traits is that they fail in different ways. A poor camera image does not affect your voice."
    );
  }
  {
    const s = content('How a face or voice is recognised', 'Design');
    const stages = [
      ['Sample', 'A camera frame or an audio clip'],
      ['Quality gate', 'Face found, sharp, lit. Speech present, not clipped'],
      ['Embedding', '128 numbers for a face, 192 for a voice'],
      ['Compare', 'Cosine similarity to the enrolled reference'],
      ['Confidence', 'Calibrated to a 0 to 1 match probability'],
    ];
    const w = 1.6, gap = 0.2;
    stages.forEach(([h, t], i) => {
      const x = 0.6 + i * (w + gap);
      s.addShape(pres.ShapeType.roundRect, { x, y: 1.3, w, h: 0.55, rectRadius: 0.08, fill: { color: i === 4 ? C.accent3 : C.accent1 }, line: { color: i === 4 ? C.accent3 : C.accent1, width: 0 } });
      tb(s, `${i + 1}  ${h}`, { x, y: 1.3, w, h: 0.55, fontSize: 15, bold: true, color: C.background1, align: 'center', valign: 'middle' });
      tb(s, t, { x: x + 0.05, y: 2.0, w: w - 0.1, h: 1.0, fontSize: 13, color: C.text2, valign: 'top', align: 'center' });
      if (i < stages.length - 1) arrow(s, x + w + 0.02, 1.575, gap - 0.04, 0);
    });
    card(s, 0.6, 3.3, 4.3, 1.55);
    tb(s, 'What is stored', { x: 0.85, y: 3.45, w: 3.9, h: 0.3, fontSize: 16, bold: true, color: C.text1 });
    tb(s, 'Only the numbers, encrypted. Photos and recordings are processed in memory and never saved.', { x: 0.85, y: 3.8, w: 3.8, h: 1.0, fontSize: 14, color: C.text2, valign: 'top' });
    card(s, 5.1, 3.3, 4.3, 1.55);
    tb(s, 'Why calibrate', { x: 5.35, y: 3.45, w: 3.9, h: 0.3, fontSize: 16, bold: true, color: C.text1 });
    tb(s, 'Face and voice scores mean different things, so each model is mapped to a match probability before we combine them.', { x: 5.35, y: 3.8, w: 3.8, h: 1.0, fontSize: 14, color: C.text2, valign: 'top' });
    s.addNotes(
      "This slide answers the question of how the system knows it is you and not just capturing a face.\n\n" +
      "When you enroll, the system checks the sample quality, then a neural network turns your face into 128 numbers, or your voice into 192 numbers. Those numbers describe your features, not the picture. Only the numbers are stored, encrypted.\n\n" +
      "When you verify, it does the same with the new sample and measures how close the new numbers are to the saved ones. Your own face gives close numbers, someone else's gives clearly different ones. Because the face model and the voice model score on different scales, I calibrate each one into a match probability before combining them. The face model is SFace, the voice model is SpeechBrain's ECAPA-TDNN."
    );
  }
  {
    const s = content('Scoring how risky a payment is', 'Design');
    const rows = [
      ['Amount', '0 to 40'], ['New recipient', '+20'], ['International', '+12'], ['New device', '+10'], ['Unusual amount for this user', '+12'],
      ['Several payments in minutes', '+10 / +20'], ['Unusual hour for this user', '+8'], ['New account, large amount', '+10'], ['Biometrics changed recently', '+12'],
    ];
    card(s, 0.6, 1.25, 4.6, 3.65);
    tb(s, 'What adds risk (points)', { x: 0.85, y: 1.38, w: 4.1, h: 0.3, fontSize: 16, bold: true, color: C.text1 });
    s.addTable(rows.map(([a, b]) => [{ text: a, options: { color: C.text2 } }, { text: b, options: { bold: true, align: 'right', color: C.text1 } }]),
      { x: 0.85, y: 1.8, w: 4.1, colW: [2.9, 1.2], fontSize: 12, rowH: 0.31, border: { type: 'none' }, margin: [0, 0, 0, 0] });
    // four-level scale
    const lv = [['Low', 'under 25', C.accent3], ['Medium', '25 to 49', C.accent1], ['High', '50 to 74', C.accent2], ['Critical', '75 and up', C.accent4]];
    tb(s, 'Four risk levels', { x: 5.5, y: 1.38, w: 3.9, h: 0.3, fontSize: 16, bold: true, color: C.text1 });
    lv.forEach(([n, r, col], i) => {
      const x = 5.5 + i * 0.98;
      s.addShape(pres.ShapeType.roundRect, { x, y: 1.85, w: 0.92, h: 0.5, rectRadius: 0.05, fill: { color: col }, line: { color: col, width: 0 } });
      tb(s, n, { x, y: 1.85, w: 0.92, h: 0.5, fontSize: 12, bold: true, color: C.background1, align: 'center', valign: 'middle' });
      tb(s, r, { x, y: 2.42, w: 0.92, h: 0.25, fontSize: 11, color: C.text2, align: 'center' });
    });
    tb(s, 'Rule based and explainable: every point is shown to the user. It is not a trained fraud model.', { x: 5.5, y: 3.1, w: 3.9, h: 0.9, fontSize: 14, color: C.text2, valign: 'top' });
    tb(s, 'The time factors learn your usual hours from your approved payments.', { x: 5.5, y: 4.1, w: 3.9, h: 0.7, fontSize: 14, italic: true, color: C.text1, valign: 'top' });
    s.addNotes(
      "The risk engine is deliberately simple and explainable. It adds points for things that make a payment riskier: a large amount, a new recipient, an international transfer, a new device, an amount that is unusual for that user.\n\n" +
      "I also added time-aware factors. Several payments within minutes, an unusual hour for that user, a brand-new account moving real money, or biometrics that were changed recently. The unusual-hour factor learns the user's usual hours from their approved payments.\n\n" +
      "The total is a score out of 100, grouped into four levels. I want to be clear that this is hand-set rules, not a trained fraud model. I have no fraud data, so I did not claim any accuracy for it. The benefit is that the app shows every factor, so the user can see why."
    );
  }
  {
    const s = content('Combining the evidence into a decision', 'Design');
    const flow = [['Evidence', 'per modality'], ['Weigh by quality', 'poor input counts less'], ['Fused score', 'plus coverage'], ['Risk sets the bar', 'thresholds per level']];
    const w = 1.95, gap = 0.33;
    flow.forEach(([h, t], i) => {
      const x = 0.6 + i * (w + gap);
      card(s, x, 1.25, w, 0.95);
      tb(s, h, { x: x + 0.1, y: 1.38, w: w - 0.2, h: 0.3, fontSize: 15, bold: true, color: C.text1, align: 'center' });
      tb(s, t, { x: x + 0.1, y: 1.7, w: w - 0.2, h: 0.3, fontSize: 12, color: C.text2, align: 'center' });
      if (i < flow.length - 1) arrow(s, x + w + 0.03, 1.72, gap - 0.06, 0);
    });
    const hdr = ['Risk', 'Approve at', 'Evidence needed'];
    const rows = [['Low', '0.60', 'any 1 biometric'], ['Medium', '0.70', 'any 2 biometrics'], ['High', '0.80', 'face and voice'], ['Critical', '0.88', 'face and voice']];
    const colr = { Low: C.accent3, Medium: C.accent1, High: C.accent2, Critical: C.accent4 };
    s.addTable([
      hdr.map((h) => ({ text: h, options: { bold: true, color: C.text2, fontSize: 12 } })),
      ...rows.map(([a, b, c]) => [{ text: a, options: { bold: true, color: colr[a] } }, { text: b, options: { color: C.text1 } }, { text: c, options: { color: C.text1 } }]),
    ], { x: 0.6, y: 2.45, w: 4.7, colW: [1.2, 1.3, 2.2], fontSize: 13, rowH: 0.38, border: { type: 'solid', pt: 0.5, color: 'D8E0EB' }, fill: { color: C.background1 }, margin: [0, 0.1, 0, 0.1] });
    const out = [['Approved', C.accent3, 'evidence is strong enough'], ['Rejected', C.accent4, 'evidence clearly does not match'], ['Ask for more', C.accent2, 'not enough evidence yet']];
    out.forEach(([h, col, t], i) => {
      const y = 2.5 + i * 0.7;
      s.addShape(pres.ShapeType.roundRect, { x: 5.7, y, w: 1.45, h: 0.5, rectRadius: 0.06, fill: { color: col }, line: { color: col, width: 0 } });
      tb(s, h, { x: 5.7, y, w: 1.45, h: 0.5, fontSize: 13, bold: true, color: C.background1, align: 'center', valign: 'middle' });
      tb(s, t, { x: 7.3, y, w: 2.1, h: 0.5, fontSize: 13, color: C.text2, valign: 'middle' });
    });
    tb(s, 'A missing or failed input is never counted as a match. Fingerprint only adds evidence when present.', { x: 0.6, y: 4.72, w: 8.8, h: 0.5, fontSize: 14, italic: true, color: C.text1, fontFace: THEME.headFontFace });
    s.addNotes(
      "This is the fusion step, the main technical part. Each modality gives a calibrated match probability and a quality value. Poor-quality input counts for less. The system combines them into one fused score and also measures coverage, which is how much of the required evidence we actually have.\n\n" +
      "Then the risk level sets the bar. Low risk needs a score of 0.60 from any one biometric. High and critical need both face and voice and a higher score. Fingerprint is optional: if it is there it adds evidence, and if it is missing nothing changes.\n\n" +
      "The outcome is approved, rejected, or additional verification. The last one matters, because when evidence is missing or unclear I do not want to call the user an attacker. I ask for more. And again, missing or failed input is never counted as a match."
    );
  }
  {
    const s = content('Security and privacy built in', 'Design');
    const items = [
      [fi.FiLock, 'Strong sign-in', 'Password, then live face and voice.'],
      [fi.FiRefreshCw, 'Liveness checks', 'Head turn and three random spoken words.'],
      [fi.FiShield, 'Smart lockouts', 'An attacker\'s failures cannot lock you out.'],
      [fi.FiKey, 'Protected enrollment', 'Changing biometrics needs the password and a matching sample.'],
      [fi.FiLifeBuoy, 'Careful recovery', 'Waiting period, admin approval, then probation.'],
      [fi.FiEyeOff, 'Privacy by default', 'No raw photos or recordings stored. Templates encrypted.'],
    ];
    for (let i = 0; i < items.length; i++) {
      const col = i % 3, row = Math.floor(i / 3);
      const x = 0.6 + col * 3.0, y = 1.3 + row * 1.85;
      card(s, x, y, 2.8, 1.65);
      await iconBadge(s, items[i][0], x + 0.2, y + 0.2, 0.56, items[i][1]);
      tb(s, items[i][1], { x: x + 0.9, y: y + 0.28, w: 1.8, h: 0.4, fontSize: 15, bold: true, color: C.text1, valign: 'middle' });
      tb(s, items[i][2], { x: x + 0.2, y: y + 0.9, w: 2.45, h: 0.7, fontSize: 13, color: C.text2, valign: 'top' });
    }
    s.addNotes(
      "Because this is an authentication system, I spent a lot of time on how it could be attacked.\n\n" +
      "Sign-in needs the password and then a live face and voice. The liveness check asks for a head turn in a random direction and three random words, so a still photo or an old recording does not work. Lockouts are tied to the device and network that failed, so an attacker cannot lock the real owner out of their own account.\n\n" +
      "Changing biometrics needs your password and fresh samples, so someone with only your password cannot swap in their own face. If you genuinely lose access, there is a recovery flow with a waiting period, admin approval and a probation period.\n\n" +
      "On privacy, raw photos and recordings are never saved. Only encrypted numbers are, and a user can erase everything. I will be honest about what liveness does not stop in the limitations slide."
    );
  }

  // section 4: workflow ---------------------------------------------------
  pres.addSection({ title: 'Implementation and workflow' });
  {
    const s = content('Setting up and signing in', 'Implementation and workflow');
    await cropFrame(s, 'enroll', 0.6, 1.3, 4.3, 'Enrollment', 'Face and voice are required, fingerprint is optional. A reference only counts once the server has built it.', 2.05);
    await cropFrame(s, 'signin', 5.1, 1.3, 4.3, 'Sign-in', 'Password first. Then a live face and voice check, with a recovery option if it cannot be passed.', 2.05);
    s.addNotes(
      "These are real screenshots from the running application.\n\n" +
      "On the left is enrollment. A new account starts with a limited session that can only see this page. Face and voice are marked required, and fingerprint is marked optional. Each card explains what to do, shows the samples you collected, and only shows Enrolled after the server has actually built a reference from a valid sample. Once face and voice are both enrolled, the rest of the app unlocks.\n\n" +
      "On the right is sign-in. After the password, the app asks for a live face and voice. The password alone opens nothing. If someone cannot pass this step, for example their face changed, there is a recovery option."
    );
  }
  {
    const s = content('A small payment, start to finish', 'Implementation and workflow');
    await cropFrame(s, 'pay-risk', 0.6, 1.3, 4.3, 'Risk assessment', 'The server scores the payment, lists every factor, and says what this level requires.', 2.4);
    await cropFrame(s, 'pay-decision', 5.1, 1.3, 4.3, 'Decision with evidence', 'Match confidence, input quality and a plain reason. A blank sample is no evidence, never a match.', 2.4);
    s.addNotes(
      "Here is an ordinary payment. In step one I enter the details and the page shows a live risk estimate with the factors, so the user can see what is adding risk.\n\n" +
      "In step two the server computes the final risk score and tells the user what this risk level requires. This one is low risk, so one biometric is enough. In step three the user verifies with the camera, and step four is the decision.\n\n" +
      "The decision page is the part I care about most. It shows the result, the match confidence for each biometric, the input quality, and a plain-language reason. A sample that was not submitted shows as no evidence, never as a match."
    );
  }
  {
    const s = content('A large payment asks for more', 'Implementation and workflow');
    await cropFrame(s, 'big-risk', 0.6, 1.3, 4.3, 'Critical risk', 'Face and voice are both required, and both must be live. Fingerprint cannot replace either.', 2.6);
    await cropFrame(s, 'big-refused', 5.1, 1.3, 4.3, 'A still camera is refused', 'No head turn was seen, so it asks for more evidence and lists exactly what to do. Three attempts.', 2.6);
    s.addNotes(
      "Now a 25,000 dollar payment to a new international recipient. The risk comes out as critical, and the app tells the user up front that face and voice are both required, and that they must be live.\n\n" +
      "In the verify step it shows a head-turn instruction and three words to say. In my browser test I used a fake camera that plays a single photo, so it never turns its head. The system correctly refuses it: no clear head turn was seen. The payment is not rejected as an attack. It asks for additional verification and lists exactly what to do next, and the user has three attempts."
    );
  }
  {
    const s = content('Seeing what happened', 'Implementation and workflow');
    await cropFrame(s, 'dashboard', 0.6, 1.3, 4.3, 'Dashboard and history', 'Totals, risk and outcomes from stored data, plus history.', 3.0);
    await cropFrame(s, 'analytics', 5.1, 1.3, 4.3, 'Analytics', 'Every figure is labelled real, synthetic or simulated.', 3.0);
    s.addNotes(
      "After payments, the user can see what happened. The dashboard shows totals, the risk distribution, outcomes, activity over time and the status of each biometric module. All of it is read from the stored data, nothing is hard-coded.\n\n" +
      "The history page lists every payment with its risk, which biometrics were evaluated, and the decision. Opening one gives the full explanation.\n\n" +
      "The analytics page shows the evaluation results, and every figure is labelled as real dataset, synthetic data or simulated, so nobody mistakes one for the other. I will go through those results shortly."
    );
  }
  {
    const s = content('How it is built and tested', 'Implementation and workflow');
    const tech = [['Frontend', 'React, Vite, Recharts'], ['Backend', 'FastAPI, SQLAlchemy, SQLite'], ['Face', 'OpenCV: YuNet + SFace'], ['Voice', 'SpeechBrain ECAPA-TDNN'], ['Spoken words', 'faster-whisper (tiny.en)'], ['Fingerprint', 'SIFT keypoints + RANSAC']];
    tech.forEach(([a, b], i) => {
      const y = 1.3 + i * 0.58;
      tb(s, a, { x: 0.6, y, w: 1.5, h: 0.4, fontSize: 14, bold: true, color: C.accent1, valign: 'middle' });
      tb(s, b, { x: 2.1, y, w: 3.0, h: 0.4, fontSize: 14, color: C.text1, valign: 'middle' });
    });
    const stats = [[TESTS, 'automated tests passing'], ['1', 'browser test of the whole flow in real Chrome'], ['10', 'random splits per evaluation']];
    stats.forEach(([n, t], i) => {
      const y = 1.25 + i * 1.2;
      card(s, 5.5, y, 3.9, 1.05);
      tb(s, n, { x: 5.7, y, w: 1.3, h: 1.05, fontSize: 38, bold: true, color: C.accent1, fontFace: THEME.headFontFace, valign: 'middle' });
      tb(s, t, { x: 7.0, y, w: 2.3, h: 1.05, fontSize: 14, color: C.text2, valign: 'middle' });
    });
    tb(s, 'Models are open source and run on a normal CPU. No paid services.', { x: 0.6, y: 4.85, w: 8.8, h: 0.3, fontSize: 12, color: C.text2 });
    s.addNotes(
      "On the implementation: the frontend is React with Vite. The backend is FastAPI with SQLite. Face recognition uses OpenCV's YuNet detector and SFace model. Voice uses SpeechBrain's ECAPA-TDNN speaker model. The spoken-word liveness check uses a small speech recognizer called faster-whisper. The fingerprint matcher uses SIFT keypoints with RANSAC. Everything runs on a normal CPU, with no paid services.\n\n" +
      "For testing, there are " + TESTS + " automated tests covering things like the risk rules, the fusion policy, access control, lockouts and privacy. I also wrote a browser test that drives the real interface in Chrome with a fake camera and microphone, and it caught real bugs, for example a camera button that did nothing if you pressed it too early. And the evaluation is reproducible: every run stores its seed and a hash of its trial list."
    );
  }

  // section 5: evaluation -------------------------------------------------
  pres.addSection({ title: 'Evaluation' });
  {
    const s = content('How we evaluated it', 'Evaluation');
    const flow = [['Public datasets', 'LFW faces, LibriSpeech voices'], ['Trials', 'genuine and impostor'], ['Split people', 'two halves, never mixed'], ['Fit on half A', 'thresholds'], ['Measure on half B', 'FAR, FRR, EER'], ['Repeat', '10 random splits']];
    const w = 1.32, gap = 0.176;
    flow.forEach(([h, t], i) => {
      const x = 0.6 + i * (w + gap);
      card(s, x, 1.3, w, 1.3);
      tb(s, h, { x: x + 0.06, y: 1.42, w: w - 0.12, h: 0.5, fontSize: 13, bold: true, color: C.text1, align: 'center', valign: 'top' });
      tb(s, t, { x: x + 0.08, y: 1.95, w: w - 0.16, h: 0.6, fontSize: 11, color: C.text2, align: 'center', valign: 'top' });
      if (i < flow.length - 1) arrow(s, x + w + 0.01, 1.95, gap - 0.02, 0);
    });
    const cardsInfo = [
      ['Real data', 'Faces from LFW and voices from Mini LibriSpeech, public datasets of real people.', C.accent3],
      ['Synthetic data', 'Fingerprints are generated. We found no real fingerprint dataset we could download.', C.accent2],
      ['What we report', 'FAR, FRR and EER with 95% confidence intervals, plus how many inputs could not be evaluated.', C.accent1],
    ];
    cardsInfo.forEach(([h, t, col], i) => {
      const x = 0.6 + i * 3.0;
      card(s, x, 2.95, 2.8, 1.95);
      s.addShape(pres.ShapeType.roundRect, { x: x + 0.2, y: 3.12, w: 1.35, h: 0.3, rectRadius: 0.15, fill: { color: col, transparency: 80 }, line: { color: col, width: 0, transparency: 100 } });
      tb(s, h, { x: x + 0.2, y: 3.12, w: 1.35, h: 0.3, fontSize: 12, bold: true, color: C.text1, align: 'center', valign: 'middle' });
      tb(s, t, { x: x + 0.2, y: 3.58, w: 2.4, h: 1.25, fontSize: 13, color: C.text2, valign: 'top' });
    });
    s.addNotes(
      "Let me explain how I measured it, because the method matters as much as the numbers.\n\n" +
      "For each biometric I built genuine trials, where the probe is the same person, and impostor trials, where it is a different person. The people are split into two halves. I fit the decision threshold on one half and measure on the other, so the threshold was never tuned on the people it is tested on. I repeat that with ten random splits to see how much the result depends on the split.\n\n" +
      "I should be upfront about the data. Faces and voices come from public datasets of real people. Fingerprints are synthetic, because I could not find a real fingerprint dataset I could download, so I do not claim anything about real fingerprints. Along the way I found and fixed some flaws in my first evaluation, for example impostor samples leaking across the two halves."
    );
  }
  {
    const s = content('Results: each biometric on its own', 'Evaluation');
    const f = D.mod_face, v = D.mod_voice, p = D.mod_fingerprint;
    const hdr = ['', 'Data', 'Trials', 'EER', 'FAR (95% CI)', 'FRR (95% CI)', 'Time'];
    const row = (name, data, m, tone) => [
      { text: name, options: { bold: true, color: C.text1 } }, { text: data, options: { color: tone } },
      { text: `${m.genuine_trials} / ${m.impostor_trials}`, options: { color: C.text1 } }, { text: pc(m.eer), options: { bold: true, color: C.text1 } },
      { text: `${pc(m.far)} (${ci(m.far_ci)})`, options: { color: C.text1 } }, { text: `${pc(m.frr)} (${ci(m.frr_ci)})`, options: { color: C.text1 } },
      { text: `${Math.round(m.latency_ms_mean)} ms`, options: { color: C.text1 } },
    ];
    s.addTable([
      hdr.map((h) => ({ text: h, options: { bold: true, color: C.text2, fontSize: 11 } })),
      row('Face', 'Real (LFW)', f, C.accent3),
      row('Voice', 'Real (LibriSpeech)', v, C.accent3),
      row('Fingerprint', 'Synthetic', p, C.accent2),
    ], { x: 0.6, y: 1.3, w: 8.8, colW: [1.2, 1.6, 0.95, 0.7, 1.7, 1.7, 0.95], fontSize: 12, rowH: 0.44, border: { type: 'solid', pt: 0.5, color: 'D8E0EB' }, fill: { color: C.background1 }, margin: [0, 0.08, 0, 0.08] });
    tb(s, 'Trials are genuine / impostor attempts. EER: false accepts equal false rejects. FAR: impostors accepted. FRR: real users rejected. CI: 95% confidence interval, in %.', { x: 0.6, y: 3.2, w: 8.8, h: 0.4, fontSize: 11, italic: true, color: C.text2, valign: 'top' });
    const call = [
      [pc(f.eer), 'face equal error rate', `${f.evaluation_subjects} people in the evaluation half`],
      [pc(v.splits.far.mean, 1) + ' ± ' + pc(v.splits.far.sd, 1), 'voice false accepts over 10 splits', `only ${v.evaluation_subjects} speakers per half`],
    ];
    call.forEach(([n, t, sub], i) => {
      const x = 0.6 + i * 4.5;
      card(s, x, 3.7, 4.3, 1.3);
      tb(s, n, { x: x + 0.25, y: 3.78, w: 3.8, h: 0.62, fontSize: 30, bold: true, color: C.accent1, fontFace: THEME.headFontFace, valign: 'middle' });
      tb(s, t, { x: x + 0.25, y: 4.4, w: 3.8, h: 0.26, fontSize: 14, bold: true, color: C.text1 });
      tb(s, sub, { x: x + 0.25, y: 4.67, w: 3.8, h: 0.26, fontSize: 12, color: C.text2 });
    });
    s.addNotes(
      "These are the results for each biometric on its own. FAR is how often an impostor is accepted, FRR is how often the real user is rejected, and EER is where the two are equal.\n\n" +
      "Face on real photos has an equal error rate of about 0.45 percent, with a false accept rate of 0.5 percent. Voice on real speech has a 0 percent EER in the main split, but I want to be careful: there are only 13 speakers in each half, so the interval on the false accept rate goes up to almost 7 percent, and across ten splits the false accept rate is 1.4 percent plus or minus 1.8. That variation is the honest picture.\n\n" +
      "The fingerprint row is synthetic data, so it only shows that the matcher works mechanically. It says nothing about real fingerprints. And all of these datasets are easier than a phone camera in a dim room, so real-world performance will be worse. I did not try to estimate by how much."
    );
  }
  {
    const s = content('When input is poor, and the liveness checks', 'Evaluation');
    const fd = D.mod_face.degraded, vd = D.mod_voice.degraded;
    const find = (arr, key) => arr.find((d) => d.condition.startsWith(key));
    const rows = [
      ['Face: mild blur', pc(find(fd, 'mild blur').not_evaluable_rate, 0) + ' refused'],
      ['Face: dim light', pc(find(fd, 'dim light').not_evaluable_rate, 0) + ' refused'],
      ['Face: strong blur, dark, low resolution', '100% refused'],
      ['Voice: noise at 10 dB', pc(find(vd, 'noise SNR 10').frr, 0) + ' real users rejected'],
      ['Voice: noise at 0 dB', pc(find(vd, 'noise SNR 0').not_evaluable_rate, 0) + ' refused'],
    ];
    card(s, 0.6, 1.25, 4.3, 3.65);
    tb(s, 'It refuses to guess', { x: 0.85, y: 1.38, w: 3.8, h: 0.3, fontSize: 16, bold: true, color: C.text1 });
    s.addTable(rows.map(([a, b]) => [{ text: a, options: { color: C.text2 } }, { text: b, options: { bold: true, color: C.text1, align: 'right' } }]),
      { x: 0.85, y: 1.85, w: 3.8, colW: [2.3, 1.5], fontSize: 12, rowH: 0.5, border: { type: 'none' }, margin: [0, 0, 0, 0] });
    tb(s, 'Too-poor input is refused instead of scored. The user is asked to retry.', { x: 0.85, y: 4.3, w: 3.8, h: 0.55, fontSize: 12, italic: true, color: C.text2, valign: 'top' });
    const L = D.liveness;
    const lf = L.face, lv = L.voice;
    const rows2 = [
      ['Tilted flat photo passes', `${lf.flat_photo_tilt_attack_passes.k} in ${lf.flat_photo_tilt_attack_passes.n}`],
      ['Two-photo swap passes', `${lf.photo_swap_attack_passes.k} in ${lf.photo_swap_attack_passes.n}`],
      ['Spoken words heard (clean audio)', pc(lv.said_words_pass_2of3.clean.rate, 0)],
      ['Spoken words heard (10 dB noise)', pc(lv.said_words_pass_2of3.n10.rate, 0)],
      ['Unrelated recording passes', `${lv.unrelated_audio_pass_2of3.k} in ${lv.unrelated_audio_pass_2of3.n}`],
    ];
    card(s, 5.1, 1.25, 4.3, 3.65);
    tb(s, 'Liveness checks', { x: 5.35, y: 1.38, w: 2.0, h: 0.3, fontSize: 16, bold: true, color: C.text1 });
    s.addShape(pres.ShapeType.roundRect, { x: 7.35, y: 1.4, w: 1.85, h: 0.27, rectRadius: 0.13, fill: { color: C.accent2, transparency: 80 }, line: { color: C.accent2, width: 0, transparency: 100 } });
    tb(s, 'simulated attacks', { x: 7.35, y: 1.4, w: 1.85, h: 0.27, fontSize: 11, bold: true, color: C.text1, align: 'center', valign: 'middle' });
    s.addTable(rows2.map(([a, b]) => [{ text: a, options: { color: C.text2 } }, { text: b, options: { bold: true, color: C.text1, align: 'right' } }]),
      { x: 5.35, y: 1.85, w: 3.8, colW: [2.7, 1.1], fontSize: 12, rowH: 0.5, border: { type: 'none' }, margin: [0, 0, 0, 0] });
    tb(s, 'Face attacks are simulated from photos. The spoken-word test uses real speech.', { x: 5.35, y: 4.3, w: 3.8, h: 0.55, fontSize: 12, italic: true, color: C.text2, valign: 'top' });
    s.addNotes(
      "Two things here. On the left, what happens when the input is poor. I blurred, darkened, shrank and added noise to the same test samples. In most cases the system does not guess. It refuses the input as not evaluable and asks the user to retry. That is deliberate: a bad image should not turn into a wrong decision. The one place where real users get rejected is voice at 10 dB noise, about 14 percent.\n\n" +
      "On the right are the liveness checks. I could not download a real spoofing dataset, so I want to be clear that the face numbers are simulated: I turned real photos into flat tilted sheets and swapped between two real photos. Only 1 in 1000 tilted photos passed and none of the swaps did. For the spoken words, I used real speech: two of three words are heard about 95 percent of the time on clean audio, and none of 650 unrelated recordings passed. These do not cover videos or voice cloning."
    );
  }
  {
    const s = content('Results: fixed threshold vs risk-aware', 'Evaluation');
    const o = D.fusion.conditions[0].overall;
    const cats = ['Attacker submits only one stolen trait', 'Honest users asked for more'];
    const data = [
      { name: 'Fixed threshold', labels: cats, values: [o.fixed.worst_omission_asr * 100, o.fixed.genuine_additional_rate * 100] },
      { name: 'Always two modalities', labels: cats, values: [o.fixed_min2.worst_omission_asr * 100, o.fixed_min2.genuine_additional_rate * 100] },
      { name: 'Risk-aware (ours)', labels: cats, values: [o.risk_aware.worst_omission_asr * 100, o.risk_aware.genuine_additional_rate * 100] },
    ];
    s.addChart(pres.charts.BAR, data, {
      x: 0.5, y: 1.2, w: 5.4, h: 3.7, barDir: 'col', barGrouping: 'clustered', barGapWidthPct: 60,
      chartColors: [HEX.accent5, HEX.accent1, HEX.accent2],
      showLegend: true, legendPos: 'b', legendFontSize: 11, legendColor: HEX.dk1, legendFontFace: '+mn-lt',
      showValue: true, dataLabelPosition: 'outEnd', dataLabelFontSize: 11, dataLabelColor: HEX.dk1, dataLabelFontFace: '+mn-lt', dataLabelFormatCode: '0.0"%"',
      catAxisLabelFontSize: 11, catAxisLabelColor: HEX.dk1, catAxisLabelFontFace: '+mn-lt',
      valAxisLabelFontSize: 10, valAxisLabelColor: HEX.accent5, valAxisLabelFontFace: '+mn-lt', valAxisMaxVal: 120, valAxisMinVal: 0, valAxisLabelFormatCode: '0"%"',
      valGridLine: { color: 'D8E0EB', size: 0.5 }, catGridLine: { style: 'none' },
    });
    const pts = [
      ['Plain threshold', 'Fooled every time when only one trait is submitted.'],
      ['Always two', 'Safe, but a good user with one trait is blocked.'],
      ['Risk-aware', 'Closes the hole for medium risk and up. Low-risk payments still accept one trait, so 40% get through.'],
    ];
    pts.forEach(([h, t], i) => {
      const y = 1.25 + i * 1.12;
      tb(s, h, { x: 6.2, y, w: 3.2, h: 0.28, fontSize: 14, bold: true, color: i === 2 ? C.accent2 : C.text1 });
      tb(s, t, { x: 6.2, y: y + 0.3, w: 3.2, h: 0.75, fontSize: 12, color: C.text2, valign: 'top' });
    });
    tb(s, 'Simulated attempts from measured scores. Fingerprint scores are synthetic.', { x: 0.6, y: 4.95, w: 8.8, h: 0.25, fontSize: 11, italic: true, color: C.text2 });
    s.addNotes(
      "This compares the decision policies using simulated attempts built from the measured scores. The fingerprint scores in it are synthetic, and the risk mix is assumed, so this shows how the policies behave, not real-world accuracy.\n\n" +
      "The attack I focused on is what I call an omission attack: the attacker has beaten one trait, say the face, and submits only that one, leaving the others blank. A plain fixed threshold averages whatever is present, so it approves that attack every time. My risk-aware policy blocks it for medium risk and above. The 40 percent that still gets through is exactly the low-risk share of my assumed mix, because low-risk payments deliberately accept one biometric.\n\n" +
      "The honest part: a simple rule that always requires two biometrics is also safe, and when all traits are present it asks honest users for less. The risk-aware policy asks about 6.8 percent of honest users for more, and about 14 to 19 percent on high and critical payments. So it is a different trade-off, not a free win. Whether low-risk single-biometric approval is acceptable is a business decision."
    );
  }

  // section 6: wrap-up ------------------------------------------------------
  pres.addSection({ title: 'Wrap-up' });
  {
    const s = content('Limitations and what comes next', 'Wrap-up');
    const L = [
      'Fingerprint was only tested on generated prints',
      'Datasets are small and easy, so real-world error will be higher',
      'Liveness does not stop videos, deepfakes or voice cloning, and was never run on a real person turning their head',
      'Prototype: simulated money, no HTTPS, SQLite',
    ];
    const N = [
      'Real fingerprint sensor and dataset',
      'Public spoofing datasets to test liveness properly',
      'On-device biometrics (WebAuthn) and HTTPS',
      'Larger multi-session datasets and tuned thresholds',
    ];
    card(s, 0.6, 1.25, 4.3, 3.65);
    tb(s, 'What we have not proven', { x: 0.85, y: 1.4, w: 3.8, h: 0.3, fontSize: 16, bold: true, color: C.accent4 });
    tb(s, L.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < L.length - 1 } })), { x: 0.85, y: 1.85, w: 3.8, h: 2.95, fontSize: 14, color: C.text2, valign: 'top', paraSpaceAfter: 6 });
    card(s, 5.1, 1.25, 4.3, 3.65);
    tb(s, 'What comes next', { x: 5.35, y: 1.4, w: 3.8, h: 0.3, fontSize: 16, bold: true, color: C.accent3 });
    tb(s, N.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < N.length - 1 } })), { x: 5.35, y: 1.85, w: 3.8, h: 2.95, fontSize: 14, color: C.text2, valign: 'top', paraSpaceAfter: 6 });
    s.addNotes(
      "I want to be honest about the limits, because I would rather you hear them from me.\n\n" +
      "Fingerprint was only tested on generated prints, so I make no claim about real fingerprints. The datasets for face and voice are small and easier than real conditions, so the real error rates will be higher. The liveness checks stop still photos and old recordings, but not a video of the user, a deepfake or voice cloning, and the head-turn check has been tested with logic tests and a fake camera but never with a real person turning their head. And it is a prototype: simulated money, no HTTPS, SQLite.\n\n" +
      "For the next steps, I would get a real fingerprint sensor and dataset, test liveness against public spoofing datasets, move to on-device biometrics with WebAuthn and HTTPS, and run on larger datasets with several sessions per person."
    );
  }
  {
    const s = pres.addSlide({ masterName: 'CLOSING_DARK', sectionTitle: 'Wrap-up' });
    s.addText('Conclusion', { placeholder: 'title' });
    const pts = [
      ['The check should match the risk.', 'TriLock raises the bar for large payments and keeps small ones smooth.'],
      ['Missing evidence is never a match.', 'Failed or missing input asks for more, it does not approve.'],
      ['We measured it, and said where it is weak.', 'Real and synthetic data are labelled, and the limits are listed.'],
    ];
    pts.forEach(([h, t], i) => {
      const y = 1.95 + i * 1.1;
      s.addShape(pres.ShapeType.ellipse, { x: 0.6, y: y + 0.03, w: 0.42, h: 0.42, fill: { color: C.accent1 }, line: { color: C.accent1, width: 0 } });
      tb(s, String(i + 1), { x: 0.6, y: y + 0.03, w: 0.42, h: 0.42, fontSize: 15, bold: true, color: C.background1, align: 'center', valign: 'middle' });
      tb(s, h, { x: 1.25, y, w: 5.3, h: 0.35, fontSize: 18, bold: true, color: C.background1 });
      tb(s, t, { x: 1.25, y: y + 0.38, w: 5.3, h: 0.55, fontSize: 14, color: C.accent6, valign: 'top' });
    });
    s.addShape(pres.ShapeType.roundRect, { x: 7.0, y: 1.9, w: 2.4, h: 2.9, rectRadius: 0.1, fill: { color: C.text2 }, line: { color: C.text2, width: 0 } });
    s.addImage({ data: await icon(fi.FiLock, HEX.accent6), x: 7.9, y: 2.3, w: 0.6, h: 0.6, altText: 'Lock' });
    tb(s, 'Thank you', { x: 7.1, y: 3.1, w: 2.2, h: 0.4, fontSize: 22, bold: true, color: C.background1, align: 'center', fontFace: THEME.headFontFace });
    tb(s, 'Questions?', { x: 7.1, y: 3.6, w: 2.2, h: 0.35, fontSize: 16, color: C.accent6, align: 'center' });
    s.addNotes(
      "To conclude. TriLock shows that the strength of the check can follow the risk of the payment: small payments stay smooth, and larger ones need more proof, with face and voice as the core and fingerprint as an optional extra.\n\n" +
      "The main rule I kept was that missing or failed evidence is never treated as a match. And I tried to be honest in how I measured it: real data and synthetic data are labelled separately, the simulated results are marked as simulated, and the limitations are written down.\n\n" +
      "Thank you, ma'am. I am happy to answer questions, and I can show any part of the running application."
    );
  }

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log('wrote', OUT);
}

build().catch((e) => { console.error(e); process.exit(1); });
