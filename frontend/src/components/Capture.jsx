import { useRef, useState } from 'react'
import { Camera, Mic, Square, Upload, X } from 'lucide-react'
import { useCamera, useRecorder } from '../lib/media'
import { Alert } from './ui'

function Picker({ accept, onFile, label }) {
  const ref = useRef(null)
  return (
    <>
      <input ref={ref} type="file" accept={accept} hidden onChange={(e) => { const f = e.target.files[0]; if (f) onFile(f); e.target.value = '' }} />
      <button type="button" className="btn" onClick={() => ref.current.click()}><Upload size={15} />{label}</button>
    </>
  )
}

// Image input from webcam or file upload. Calls onChange(blob | null).
export function ImageCapture({ value, onChange, accept = 'image/*', allowCamera = true, uploadLabel = 'Upload image' }) {
  const cam = useCamera()
  const [url, setUrl] = useState(null)
  const set = (blob) => {
    if (url) URL.revokeObjectURL(url)
    setUrl(blob ? URL.createObjectURL(blob) : null)
    onChange(blob)
  }
  return (
    <div className="stack">
      {cam.error && <Alert kind="warn">{cam.error}</Alert>}
      {cam.active && <video ref={cam.videoRef} className="video" playsInline muted />}
      {!cam.active && url && <img src={url} alt="Selected sample" className="preview" />}
      <div className="row">
        {allowCamera && !cam.active && <button type="button" className="btn" onClick={cam.start}><Camera size={15} />Use camera</button>}
        {cam.active && (
          <>
            <button type="button" className="btn primary" onClick={async () => { const b = await cam.snapshot(); if (b) { set(b); cam.stop() } }}><Camera size={15} />Capture</button>
            <button type="button" className="btn" onClick={cam.stop}><X size={15} />Close camera</button>
          </>
        )}
        {!cam.active && <Picker accept={accept} label={uploadLabel} onFile={set} />}
        {value && !cam.active && <button type="button" className="btn sm" onClick={() => set(null)}>Clear</button>}
      </div>
    </div>
  )
}

// Audio input from microphone (converted to 16 kHz WAV in-browser) or file upload.
export function AudioCapture({ value, onChange }) {
  const rec = useRecorder()
  const [url, setUrl] = useState(null)
  const set = (blob) => {
    if (url) URL.revokeObjectURL(url)
    setUrl(blob ? URL.createObjectURL(blob) : null)
    onChange(blob)
  }
  return (
    <div className="stack">
      {rec.error && <Alert kind="warn">{rec.error}</Alert>}
      {rec.recording && <Alert kind="info">Recording… {rec.seconds}s. Speak naturally for at least 3 seconds.</Alert>}
      {!rec.recording && url && <audio controls src={url} style={{ width: '100%' }} />}
      <div className="row">
        {!rec.recording && <button type="button" className="btn" onClick={rec.start}><Mic size={15} />Record</button>}
        {rec.recording && <button type="button" className="btn primary" onClick={async () => { const b = await rec.stop(); if (b) set(b) }}><Square size={15} />Stop</button>}
        {!rec.recording && <Picker accept="audio/wav,audio/x-wav,audio/flac,audio/ogg,.wav,.flac,.ogg" label="Upload audio" onFile={set} />}
        {value && !rec.recording && <button type="button" className="btn sm" onClick={() => set(null)}>Clear</button>}
      </div>
    </div>
  )
}
