import { useCallback, useEffect, useRef, useState } from 'react'

// ---- errors -------------------------------------------------------------
export function describeMediaError(e) {
  if (!navigator.mediaDevices?.getUserMedia)
    return 'This browser (or an insecure http page) does not allow camera/microphone access. Use localhost or https, or upload a file instead.'
  switch (e?.name) {
    case 'NotAllowedError': return 'Permission was denied. Allow access in the browser address bar, or upload a file instead.'
    case 'NotFoundError': return 'No camera or microphone was found on this device. Upload a file instead.'
    case 'NotReadableError': return 'The device is in use by another application.'
    default: return `Could not start the device (${e?.name || 'unknown error'}). Upload a file instead.`
  }
}

// ---- camera -------------------------------------------------------------
// `videoRef` is a callback ref: the stream is attached whenever the <video> element mounts, and `ready` turns true
// only once the element really has a picture, so the UI can keep Capture disabled until then.
export function useCamera() {
  const elRef = useRef(null)
  const streamRef = useRef(null)
  const [state, setState] = useState({ active: false, ready: false, starting: false, error: null })

  const attach = useCallback((el) => {
    elRef.current = el
    if (el && streamRef.current) {
      el.srcObject = streamRef.current
      el.onloadeddata = () => setState((s) => ({ ...s, ready: true }))
      el.play().catch(() => {})
    }
  }, [])

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    setState({ active: false, ready: false, starting: false, error: null })
  }, [])

  const start = useCallback(async () => {
    setState({ active: false, ready: false, starting: true, error: null })
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('unsupported')
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: 'user' } })
      streamRef.current = stream
      attach(elRef.current)       // the <video> is already mounted while "starting", so attach the stream now
      setState({ active: true, ready: false, starting: false, error: null })
    } catch (e) {
      setState({ active: false, ready: false, starting: false, error: describeMediaError(e) })
    }
  }, [attach])

  useEffect(() => () => streamRef.current?.getTracks().forEach((t) => t.stop()), [])

  // Waits up to ~3 s for a first frame, then grabs it. Resolves null if the camera never produced a picture.
  const snapshot = useCallback(async () => {
    for (let i = 0; i < 30; i++) {
      const v = elRef.current
      if (v && v.videoWidth > 0 && v.readyState >= 2) break
      await new Promise((r) => setTimeout(r, 100))
    }
    const v = elRef.current
    if (!v || !v.videoWidth) return null
    const c = document.createElement('canvas')
    c.width = v.videoWidth
    c.height = v.videoHeight
    c.getContext('2d').drawImage(v, 0, 0)
    return new Promise((resolve) => c.toBlob((b) => resolve(b && Object.assign(b, { name: 'camera.jpg' })), 'image/jpeg', 0.92))
  }, [])

  // Capture n frames, `intervalMs` apart, for the head-turn liveness challenge.
  const burst = useCallback(async (n = 10, intervalMs = 300, onFrame = () => {}) => {
    const frames = []
    for (let i = 0; i < n; i++) {
      const b = await snapshot()
      if (b) frames.push(Object.assign(b, { name: `frame${i}.jpg` }))
      onFrame(i + 1)
      await new Promise((r) => setTimeout(r, intervalMs))
    }
    return frames
  }, [snapshot])

  return { videoRef: attach, ...state, start, stop, snapshot, burst }
}

// ---- microphone -> 16 kHz mono WAV ---------------------------------------
// The server has no ffmpeg, so we decode whatever MediaRecorder produced and re-encode as WAV here.
function encodeWav(samples, sampleRate) {
  const buf = new ArrayBuffer(44 + samples.length * 2)
  const v = new DataView(buf)
  const str = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)))
  str(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); str(8, 'WAVE'); str(12, 'fmt ')
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true)
  v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true)
  str(36, 'data'); v.setUint32(40, samples.length * 2, true)
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return new Blob([buf], { type: 'audio/wav' })
}

async function toWav16k(blob) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)()
  try {
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer())
    const off = new OfflineAudioContext(1, Math.ceil(decoded.duration * 16000), 16000)
    const src = off.createBufferSource()
    src.buffer = decoded
    src.connect(off.destination)
    src.start()
    const rendered = await off.startRendering()
    return Object.assign(encodeWav(rendered.getChannelData(0), 16000), { name: 'voice.wav' })
  } finally {
    ctx.close()
  }
}

export function useRecorder() {
  const cur = useRef(null)
  const chunks = useRef([])
  const timer = useRef(null)
  const [state, setState] = useState({ recording: false, seconds: 0, error: null })

  const start = useCallback(async () => {
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('unsupported')
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false } })
      const rec = new MediaRecorder(stream)
      chunks.current = []
      rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data)
      rec.start()
      cur.current = { rec, stream }
      setState({ recording: true, seconds: 0, error: null })
      timer.current = setInterval(() => setState((s) => ({ ...s, seconds: s.seconds + 1 })), 1000)
    } catch (e) {
      setState({ recording: false, seconds: 0, error: describeMediaError(e) })
    }
  }, [])

  const stop = useCallback(() => new Promise((resolve) => {
    clearInterval(timer.current)
    const c = cur.current
    if (!c) return resolve(null)
    c.rec.onstop = async () => {
      c.stream.getTracks().forEach((t) => t.stop())
      cur.current = null
      try {
        const wav = await toWav16k(new Blob(chunks.current, { type: c.rec.mimeType }))
        setState((s) => ({ ...s, recording: false, error: null }))
        resolve(wav)
      } catch {
        setState((s) => ({ ...s, recording: false, error: 'The recording could not be converted to WAV. Upload a WAV file instead.' }))
        resolve(null)
      }
    }
    c.rec.stop()
  }), [])

  useEffect(() => () => {
    clearInterval(timer.current)
    cur.current?.stream.getTracks().forEach((t) => t.stop())
  }, [])

  return { ...state, start, stop }
}
