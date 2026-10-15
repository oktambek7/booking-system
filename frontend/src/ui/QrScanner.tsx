import { useEffect, useRef, useState } from 'react'
import { createPresenceGate, parseTicketCode } from '../qrScan'

type State = 'starting' | 'scanning' | 'denied' | 'unsupported' | 'error'

const MESSAGES: Record<State, string> = {
  starting: 'Kamera ishga tushmoqda…',
  scanning: 'QR kodni ramka ichiga joylashtiring',
  denied: 'Kameradan foydalanishga ruxsat berilmagan. Brauzer sozlamalarida ruxsat bering yoki kodni qo‘lda kiriting.',
  unsupported: 'Bu qurilma yoki brauzerda kamera mavjud emas. Kodni qo‘lda kiriting.',
  error: 'Kamerani ishga tushirib bo‘lmadi. Kodni qo‘lda kiriting.',
}

const SCAN_INTERVAL_MS = 160
const MAX_FRAME_WIDTH = 640
const ABSENT_MS = 1200

/**
 * Live camera preview that reads ticket QR codes. Each ticket is reported once each time it comes into view (`onCode`), and nothing is
 * reported while `paused` (a check-in is in flight). The decoder is loaded on demand so customers never download it.
 */
export default function QrScanner({ onCode, paused }: { onCode: (code: string) => void; paused: boolean }) {
  const video = useRef<HTMLVideoElement>(null)
  const [state, setState] = useState<State>('starting')
  const latest = useRef({ onCode, paused })
  latest.current = { onCode, paused }

  useEffect(() => {
    if (!navigator.mediaDevices?.getUserMedia) { setState('unsupported'); return undefined }
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let stream: MediaStream | undefined
    const canvas = document.createElement('canvas')
    const context = canvas.getContext('2d', { willReadFrequently: true })
    const gate = createPresenceGate(ABSENT_MS)

    async function start() {
      try {
        const { default: decode } = await import('jsqr')
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false })
        if (cancelled) { stream.getTracks().forEach((track) => track.stop()); return }
        const element = video.current
        if (!element || !context) { setState('error'); return }
        element.srcObject = stream
        await element.play()
        setState('scanning')
        const tick = () => {
          if (cancelled) return
          if (!latest.current.paused && element.readyState >= 2 && element.videoWidth > 0) {
            const scale = Math.min(1, MAX_FRAME_WIDTH / element.videoWidth)
            canvas.width = Math.round(element.videoWidth * scale)
            canvas.height = Math.round(element.videoHeight * scale)
            context.drawImage(element, 0, 0, canvas.width, canvas.height)
            const frame = context.getImageData(0, 0, canvas.width, canvas.height)
            const found = decode(frame.data, frame.width, frame.height, { inversionAttempts: 'dontInvert' })
            const code = found ? parseTicketCode(found.data) : null
            if (gate.accept(code) && code) latest.current.onCode(code)
          }
          timer = setTimeout(tick, SCAN_INTERVAL_MS)
        }
        tick()
      } catch (error) {
        if (!cancelled) setState(error instanceof DOMException && error.name === 'NotAllowedError' ? 'denied' : 'error')
      }
    }
    void start()
    return () => {
      cancelled = true
      clearTimeout(timer)
      stream?.getTracks().forEach((track) => track.stop())
    }
  }, [])

  return (
    <div className="operator-scanner">
      <div className="operator-scanner-view" data-state={state}>
        <video ref={video} muted playsInline aria-label="Kamera ko‘rinishi" />
        {state === 'scanning' && <span className="operator-scanner-frame" aria-hidden="true" />}
      </div>
      <p className={state === 'scanning' || state === 'starting' ? 'operator-scanner-hint' : 'dialog-error'} role="status">{MESSAGES[state]}</p>
    </div>
  )
}
