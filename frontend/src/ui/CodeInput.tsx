import { useRef, useState, type ClipboardEvent, type KeyboardEvent } from 'react'

type CodeInputProps = {
  /** Field name submitted with the surrounding form (a hidden input carries the joined value). */
  name?: string
  label: string
  length?: number
  value?: string
  onChange?: (value: string) => void
  autoFocus?: boolean
}

/** One-time code field: separate boxes with auto-advance, backspace-to-previous and paste support. */
export default function CodeInput({ name, label, length = 4, value, onChange, autoFocus }: CodeInputProps) {
  const [inner, setInner] = useState('')
  const code = (value ?? inner).slice(0, length)
  const boxes = useRef<Array<HTMLInputElement | null>>([])
  const commit = (next: string) => { setInner(next); onChange?.(next) }
  const focusBox = (index: number) => boxes.current[Math.max(0, Math.min(length - 1, index))]?.focus()

  const type = (index: number, raw: string) => {
    const digits = raw.replace(/\D/g, '')
    if (!digits) { commit(code.slice(0, index) + code.slice(index + 1)); return }
    const next = (code.slice(0, index) + digits + code.slice(index + 1)).slice(0, length)
    commit(next)
    focusBox(Math.min(index + digits.length, length - 1))
  }
  const onKeyDown = (index: number, event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Backspace' && !code[index] && index > 0) { event.preventDefault(); commit(code.slice(0, index - 1) + code.slice(index)); focusBox(index - 1) }
    else if (event.key === 'ArrowLeft') { event.preventDefault(); focusBox(index - 1) }
    else if (event.key === 'ArrowRight') { event.preventDefault(); focusBox(index + 1) }
  }
  const onPaste = (event: ClipboardEvent<HTMLInputElement>) => {
    const digits = event.clipboardData.getData('text').replace(/\D/g, '').slice(0, length)
    if (!digits) return
    event.preventDefault()
    commit(digits)
    focusBox(Math.min(digits.length, length - 1))
  }

  return (
    <div className="code-input" role="group" aria-label={label}>
      {Array.from({ length }, (_, index) => (
        <input
          key={index}
          ref={node => { boxes.current[index] = node }}
          value={code[index] ?? ''}
          inputMode="numeric"
          autoComplete={index === 0 ? 'one-time-code' : 'off'}
          autoFocus={autoFocus && index === 0}
          maxLength={length}
          pattern="[0-9]"
          required
          aria-label={`${label} ${index + 1}`}
          placeholder="•"
          onChange={event => type(index, event.target.value)}
          onKeyDown={event => onKeyDown(index, event)}
          onPaste={onPaste}
          onFocus={event => event.target.select()}
        />
      ))}
      {name && <input type="hidden" name={name} value={code} />}
    </div>
  )
}
