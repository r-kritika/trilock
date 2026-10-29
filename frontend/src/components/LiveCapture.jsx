import { useState } from 'react'
import { ArrowLeft, ArrowRight, Camera, X } from 'lucide-react'
import { useCamera } from '../lib/media'
import { Alert, Meter, Spinner } from './ui'

// Head-turn challenge: shows the instruction, films ~3 seconds, hands the frames to the parent.
export function LiveFace({ challenge, frames, onChange }) {
  const cam = useCamera()
  const [progress, setProgress] = useState(0)
  const [busy, setBusy] = useState(false)
  const dir = challenge?.face.direction
  const Arrow = dir === 'left' ? ArrowLeft : ArrowRight

  const run = async () => {
    setBusy(true); setProgress(0)
    const got = await cam.burst(10, 300, setProgress)
    setBusy(false)
    if (got.length >= 6) { onChange(got); cam.stop() } else onChange([])
  }
  return (
    <div className="stack-sm">
      {cam.error && <Alert kind="warn">{cam.error} A live check needs the camera; uploads are not accepted here.</Alert>}
      {!challenge && <p className="small muted row"><Spinner />Preparing the challenge…</p>}
      {challenge && (
        <div className="alert info" style={{ alignItems: 'center' }}>
          <Arrow size={20} />
          <div><strong>Turn your head slowly to YOUR {dir}</strong>, then hold. Start facing the camera and move over about two seconds.</div>
        </div>
      )}
      {(cam.active || cam.starting) && (
        <div className="video-wrap">
          <video ref={cam.videoRef} className="video" playsInline muted />
          {cam.ready && <div className="video-guide" aria-hidden />}
          {!cam.ready && <div className="overlay"><div><Spinner /><div style={{ marginTop: 8 }}>Starting camera…</div></div></div>}
        </div>
      )}
      {frames.length > 0 && !cam.active && <p className="small"><span className="badge b-ok">{frames.length} frames captured</span> <span className="muted">Record again to retry.</span></p>}
      {busy && <Meter value={progress / 10} thick />}
      <div className="row">
        {!cam.active && !cam.starting && <button type="button" className="btn" onClick={cam.start} disabled={!challenge}><Camera size={15} />{frames.length ? 'Open camera again' : 'Open camera'}</button>}
        {cam.active && <button type="button" className="btn primary" disabled={busy || !cam.ready} onClick={run}><Camera size={15} />{busy ? 'Recording…' : `Start, then turn ${dir}`}</button>}
        {cam.active && !busy && <button type="button" className="btn ghost" onClick={cam.stop}><X size={15} />Close</button>}
        {frames.length > 0 && !busy && !cam.active && <button type="button" className="btn ghost sm" onClick={() => onChange([])}>Clear</button>}
      </div>
    </div>
  )
}

export function PhraseBanner({ challenge }) {
  if (!challenge) return null
  return (
    <div className="subcard" style={{ textAlign: 'center' }}>
      <div className="xs faint" style={{ letterSpacing: '.08em', textTransform: 'uppercase' }}>Say these words clearly</div>
      <div style={{ fontSize: '1.5rem', fontWeight: 650, letterSpacing: '.02em', marginTop: 4 }}>{challenge.voice.phrase.join('   ')}</div>
    </div>
  )
}
