// Browser end-to-end test: drives the real UI in Chrome with a fake camera and microphone.
//   BASE=http://localhost:5174 MEDIA=/path/to/media node e2e/smoke.mjs
// MEDIA must hold face_a.y4m (the user's camera) and voice_a.wav (the user's microphone).
// The backend under test must run with TRILOCK_LOGIN_LIVENESS=false (a fake camera that plays one photo cannot
// perform a head turn). Set STRICT=1 against a backend with liveness ON to test that sign-in refuses instead.
// Needs Google Chrome (CHROME=/usr/bin/google-chrome).
import { chromium } from 'playwright-core'
import fs from 'node:fs'

const BASE = process.env.BASE || 'http://localhost:5174'
const MEDIA = process.env.MEDIA || '/tmp/e2e5/media'
const STRICT = process.env.STRICT === '1'
const SHOTS = process.env.SHOTS || new URL('../../docs/screenshots/', import.meta.url).pathname
const EMAIL = `e2e${Date.now()}@example.com`
const PASSWORD = 'correct-horse-battery'
fs.mkdirSync(SHOTS, { recursive: true })

const browser = await chromium.launch({
  executablePath: process.env.CHROME || '/usr/bin/google-chrome',
  headless: true,
  args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
    `--use-file-for-fake-video-capture=${MEDIA}/face_a.y4m`, `--use-file-for-fake-audio-capture=${MEDIA}/voice_a.wav`,
    '--autoplay-policy=no-user-gesture-required'],
})
const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } })
const page = await ctx.newPage()
const consoleErrors = []
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') consoleErrors.push(`${m.type()}: ${m.text()}`) })
page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`))

let failures = 0
async function step(name, fn) {
  try { await fn(); console.log(`PASS  ${name}`) }
  catch (e) {
    failures++
    console.log(`FAIL  ${name}\n      ${String(e.message).split('\n')[0]}`)
    await page.screenshot({ path: `${SHOTS}FAIL-${name.replace(/\W+/g, '_').slice(0, 60)}.png` }).catch(() => {})
  }
}
// let page transitions and toasts settle so the screenshots are not captured mid-animation
const shot = async (n) => { await page.evaluate(() => window.scrollTo(0, 0)); await page.waitForTimeout(700); await page.screenshot({ path: `${SHOTS}${n}.png`, fullPage: false }) }
const tid = (id) => page.getByTestId(id)
const btn = (scope, name) => scope.getByRole('button', { name })

async function cameraCapture(scope) {
  await btn(scope, /Use camera|Retake with camera/).first().click()
  await scope.locator('video').waitFor({ timeout: 10000 })
  const capture = btn(scope, 'Capture')
  await capture.waitFor({ timeout: 10000 })
  await page.waitForFunction((el) => !el.disabled, await capture.elementHandle(), { timeout: 15000 })   // enabled once the camera has a picture
  await capture.click()
}
async function record(scope, seconds = 5) {
  await btn(scope, /^Record/).first().click()
  await page.waitForTimeout(seconds * 1000)
  const stop = btn(scope, 'Stop')
  await page.waitForFunction((el) => !el.disabled, await stop.elementHandle(), { timeout: 10000 })
  await stop.click()
}
const noHorizontalScroll = async (label) => {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  if (over > 1) throw new Error(`${label}: page scrolls horizontally by ${over}px`)
}

await step('register: a new account lands on a limited enrollment page', async () => {
  await page.goto(BASE)
  await page.getByRole('button', { name: /Need an account/ }).click()
  await page.getByLabel('Full name').fill('E2E Tester')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password').fill(PASSWORD)
  await shot('00-register')
  await page.getByRole('button', { name: 'Create account' }).click()
  await page.getByText('Finish setting up your account').waitFor({ timeout: 20000 })
  if (await page.locator('nav').getByRole('link', { name: 'New payment' }).count()) throw new Error('payments menu visible in a limited session')
  await shot('01-enrollment-start')
})

await step('enroll face with the camera (required)', async () => {
  await page.locator('#pw').fill(PASSWORD)
  const face = tid('enroll-face')
  await face.getByText('Required', { exact: true }).first().waitFor()
  await cameraCapture(face)
  await face.getByText(/sample\(s\) ready to enroll/).waitFor({ timeout: 10000 })
  await btn(face, 'Enroll').click()
  await face.getByText('Enrolled', { exact: true }).first().waitFor({ timeout: 25000 })
  await shot('02-face-enrolled')
})

await step('enroll voice with the microphone; the app unlocks with a confirmation', async () => {
  await cameraCapture(tid('proof-face'))
  await tid('proof-face').getByText('Sample ready').waitFor({ timeout: 10000 })
  const voice = tid('enroll-voice')
  await record(voice)
  await voice.getByText(/sample\(s\) ready to enroll/).waitFor({ timeout: 15000 })
  await btn(voice, 'Enroll').click()
  await page.getByText('Your account is unlocked').waitFor({ timeout: 40000 })
  await page.locator('nav').getByRole('link', { name: 'New payment' }).waitFor({ timeout: 15000 })
  await shot('03-unlocked-dashboard')
})

await step('fingerprint is optional and nothing asks for it', async () => {
  await page.locator('nav').getByRole('link', { name: 'Enrollment' }).click()
  await tid('enroll-fingerprint').getByText('Optional', { exact: true }).first().waitFor()
  await page.getByText('Everything required is enrolled').waitFor()
  await shot('04-enrollment-complete')
})

await step('payment flow: details, risk, verify, approved', async () => {
  await page.locator('nav').getByRole('link', { name: 'New payment' }).click()
  await page.getByLabel('Amount (USD)').fill('80')
  await page.getByLabel('Recipient name').fill('Corner Cafe')
  await page.getByLabel('Recipient account').fill('CAFE001')
  await page.getByText('Live risk estimate').waitFor()
  await page.locator('.gauge-score').waitFor({ timeout: 10000 })
  await shot('05-payment-details')
  await page.getByRole('button', { name: /Calculate risk and continue/ }).click()
  await page.getByText('Risk assessment').waitFor({ timeout: 15000 })
  await shot('06-payment-risk')
  await page.getByRole('button', { name: /Continue to verification/ }).click()
  const face = tid('verify-face')
  await cameraCapture(face)
  await face.locator('img.preview').waitFor({ timeout: 10000 })
  await shot('07-payment-verify')
  await page.getByRole('button', { name: /Verify and decide/ }).click()
  await page.getByRole('heading', { name: 'Approved' }).waitFor({ timeout: 30000 })
  await page.getByText('Biometric evidence').waitFor()
  await shot('08-decision-approved')
})

await step('high-risk payment requires the live challenge and refuses a still camera', async () => {
  await page.getByRole('button', { name: /New payment/ }).click()
  await page.getByLabel('Amount (USD)').fill('25000')
  await page.getByLabel('Recipient name').fill('Offshore Ltd')
  await page.getByLabel('Recipient account').fill('X9999')
  await page.getByLabel(/Recipient is new/).check()
  await page.getByLabel(/International recipient/).check()
  await page.getByRole('button', { name: /Calculate risk and continue/ }).click()
  await page.getByText(/What (high|critical)-risk payments require/).waitFor({ timeout: 15000 })
  await shot('09-high-risk-assessment')
  await page.getByRole('button', { name: /Continue to verification/ }).click()
  await page.getByText('Live check required').waitFor({ timeout: 15000 })
  const face = tid('verify-face')
  await btn(face, 'Open camera').click()
  await face.locator('video').waitFor({ timeout: 10000 })
  const start = page.getByRole('button', { name: /Start, then turn/ })
  await page.waitForFunction((el) => !el.disabled, await start.elementHandle(), { timeout: 15000 })
  await start.click()
  await page.getByText(/frames captured/).waitFor({ timeout: 20000 })
  await shot('10-live-challenge')
  await page.getByRole('button', { name: /Verify and decide/ }).click()
  await page.getByText(/No clear head turn/).first().waitFor({ timeout: 30000 })
  await page.getByText('What to do next').waitFor()
  await shot('11-liveness-refused')
})

await step('history list and detail page', async () => {
  await page.locator('nav').getByRole('link', { name: 'History' }).click()
  await page.getByText('Offshore Ltd').first().waitFor({ timeout: 10000 })
  await shot('12-history')
  await page.getByText('Corner Cafe').first().click()
  await page.getByText('How the decision was made').waitFor({ timeout: 10000 })
  await shot('13-transaction-detail')
})

await step('analytics tabs show real, synthetic and simulated data clearly', async () => {
  await page.locator('nav').getByRole('link', { name: 'Analytics' }).click()
  await page.getByText('Real dataset').first().waitFor({ timeout: 10000 })
  await shot('14-analytics-overview')
  for (const [tab, marker, name] of [['Biometric modules', 'Module comparison', '15-analytics-modules'], ['Degraded inputs', 'Could not be evaluated', '16-analytics-robustness'],
    ['Fusion policies', 'Security versus friction', '17-analytics-fusion'], ['Liveness', 'No spoofing dataset was available', '18-analytics-liveness'], ['Rules and demos', 'Decision rules in force', '19-analytics-rules']]) {
    await page.getByRole('tab', { name: tab }).click()
    await page.getByText(marker).first().waitFor({ timeout: 10000 })
    await shot(name)
  }
})

await step('dashboard reflects the stored data', async () => {
  await page.locator('nav').getByRole('link', { name: 'Dashboard' }).click()
  await page.getByRole('heading', { name: 'Security overview' }).waitFor({ timeout: 10000 })
  await page.getByText('Activity, last 14 days').waitFor()
  const total = await page.locator('.stat-value').first().innerText()
  if (!/^[1-9]/.test(total.trim())) throw new Error(`expected a non-zero transaction total, saw "${total}"`)
  await shot('20-dashboard')
})

await step('mobile layout: drawer menu works and no page scrolls sideways', async () => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const [path, label] of [['/', 'dashboard'], ['/enroll', 'enrollment'], ['/transact', 'payment'], ['/history', 'history'], ['/analytics', 'analytics']]) {
    await page.goto(BASE + path)
    await page.waitForTimeout(1200)
    await noHorizontalScroll(label)
  }
  await page.goto(BASE + '/')
  await page.getByRole('button', { name: 'Open menu' }).click()
  await page.locator('nav').getByRole('link', { name: 'History' }).waitFor()
  await shot('21-mobile-menu')
  await page.locator('nav').getByRole('link', { name: 'History' }).click()
  await page.waitForTimeout(600)
  await shot('22-mobile-history')
  await page.setViewportSize({ width: 820, height: 1100 })
  await page.goto(BASE + '/analytics')
  await page.waitForTimeout(1000)
  await noHorizontalScroll('analytics at tablet width')
  await page.setViewportSize({ width: 1360, height: 900 })
})

await step('sign out; sign in needs the password and then face and voice', async () => {
  await page.goto(BASE + '/')
  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByText(/Verify it is you/).waitFor({ timeout: 15000 })
  await shot('23-login-biometric-step')
  if (await page.locator('nav').count()) throw new Error('app opened after the password alone')
  const faceCard = page.locator('.mod').filter({ has: page.getByRole('heading', { name: /1\. Face/ }) })
  const voiceCard = page.locator('.mod').filter({ has: page.getByRole('heading', { name: /2\. Voice/ }) })
  if (STRICT) {
    await btn(faceCard, 'Open camera').click()
    await faceCard.locator('video').waitFor({ timeout: 10000 })
    const start = page.getByRole('button', { name: /Start, then turn/ })
    await page.waitForFunction((el) => !el.disabled, await start.elementHandle(), { timeout: 15000 })
    await start.click()
    await page.getByText(/frames captured/).waitFor({ timeout: 20000 })
    await record(voiceCard)
    await page.getByRole('button', { name: 'Verify and sign in' }).click()
    await page.getByText(/could not both be confirmed/).waitFor({ timeout: 40000 })
    await shot('24-login-refused')
    return
  }
  await cameraCapture(faceCard)
  await faceCard.locator('img.preview').waitFor({ timeout: 10000 })
  await record(voiceCard)
  await page.getByRole('button', { name: 'Verify and sign in' }).click()
  await page.getByRole('heading', { name: 'Security overview' }).waitFor({ timeout: 40000 })
})

const ignorable = /Failed to load resource.*(401|403|409|422|429)/
const real = consoleErrors.filter((e) => !ignorable.test(e))
if (real.length) {
  failures++
  console.log('\nFAIL  console errors or warnings:\n  ' + [...new Set(real)].slice(0, 10).join('\n  '))
}
await browser.close()
console.log(failures ? `\n${failures} problem(s)` : '\nall steps passed, console clean')
process.exit(failures ? 1 : 0)
