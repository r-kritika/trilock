import { useEffect, useRef, useState } from 'react'
import { Camera, Mic, RotateCcw, Square, Upload, X } from 'lucide-react'
import { useCamera, useRecorder } from '../lib/media'
import { Alert, Spinner } from './ui'

function Picker({ accept, onFile, label }) {
  const ref = useRef(null)
  return (
    <>
      <input ref={ref} type="file" accept={accept} hidden onChange={(e) => { const f = e.target.files[0]; if (f) onFile(f); e.target.value = '' }} />
      <button type="button" className="btn" onClick={() => ref.current.click()}><Upload size={15} />{label}</button>
    </>
  )
}

// Image input from the webcam or a file. Calls onChange(blob | null). Capture stays disabled until the camera
// really has a picture, and says so if it never does.
export function ImageCapture({ value, onChange, accept = 'image/*', allowCamera = true, uploadLabel = 'Upload image', guide = false }) {
  const cam = useCamera()
  const [url, setUrl] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  const set = (blob) => { setUrl(blob ? URL.createObjectURL(blob) : null); onChange(blob) }
  const capture = async () => {
    setErr(null)
    const b = await cam.snapshot()
    if (!b) { setErr('The camera has not produced a picture yet. Wait a second and try again.'); return }
    set(b); cam.stop()
  }
  return (
    <div className="stack-sm">
      {cam.error && <Alert kind="warn">{cam.error}</Alert>}
      {err && <Alert kind="warn">{err}</Alert>}
      {(cam.active || cam.starting) && (
        <div className="video-wrap">
          <video ref={cam.videoRef} className="video" playsInline muted />
          {guide && cam.ready && <div className="video-guide" aria-hidden />}
          {!cam.ready && <div className="overlay"><div><Spinner /><div style={{ marginTop: 8 }}>Starting camera…</div></div></div>}
        </div>
      )}
      {!cam.active && !cam.starting && url && <img src={url} alt="Selected sample" className="preview" />}
      <div className="row">
        {allowCamera && !cam.active && !cam.starting && <button type="button" className="btn" onClick={cam.start}><Camera size={15} />{url ? 'Retake with camera' : 'Use camera'}</button>}
        {cam.active && <button type="button" className="btn primary" disabled={!cam.ready} onClick={capture}><Camera size={15} />Capture</button>}
        {cam.active && <button type="button" className="btn ghost" onClick={cam.stop}><X size={15} />Close camera</button>}
        {!cam.active && !cam.starting && <Picker accept={accept} label={uploadLabel} onFile={set} />}
        {value && !cam.active && <button type="button" className="btn ghost sm" onClick={() => set(null)}><RotateCcw size={13} />Clear</button>}
      </div>
    </div>
  )
}

// Audio from the microphone (converted to 16 kHz WAV in the browser) or a file.
export function AudioCapture({ value, onChange, minSeconds = 3 }) {
  const rec = useRecorder()
  const [url, setUrl] = useState(null)
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  const set = (blob) => { setUrl(blob ? URL.createObjectURL(blob) : null); onChange(blob) }
  const tooShort = rec.recording && rec.seconds < minSeconds
  return (
    <div className="stack-sm">
      {rec.error && <Alert kind="warn">{rec.error}</Alert>}
      {rec.recording && (
        <div className="subcard row between" style={{ padding: '10px 14px' }}>
          <span className="row" style={{ gap: 8 }}><span className="rec-dot" />Recording <strong className="mono">{String(Math.floor(rec.seconds / 60)).padStart(2, '0')}:{String(rec.seconds % 60).padStart(2, '0')}</strong></span>
          <span className="small muted">{tooShort ? `Keep speaking, at least ${minSeconds} seconds` : 'Stop when you are done'}</span>
        </div>
      )}
      {!rec.recording && url && <audio controls src={url} style={{ width: '100%' }} />}
      <div className="row">
        {!rec.recording && <button type="button" className="btn" onClick={rec.start}><Mic size={15} />{url ? 'Record again' : 'Record'}</button>}
        {rec.recording && <button type="button" className="btn primary" disabled={tooShort} onClick={async () => { const b = await rec.stop(); if (b) set(b) }}><Square size={14} />Stop</button>}
        {!rec.recording && <Picker accept="audio/wav,audio/x-wav,audio/flac,audio/ogg,.wav,.flac,.ogg" label="Upload audio" onFile={set} />}
        {value && !rec.recording && <button type="button" className="btn ghost sm" onClick={() => set(null)}><RotateCcw size={13} />Clear</button>}
      </div>
    </div>
  )
}
