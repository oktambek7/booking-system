import { createElement, useEffect, useRef, type CSSProperties, type ReactNode } from 'react'

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'

type ModalProps = {
  /** Class on the dialog surface itself. */
  className?: string
  /** Extra class on the scrim that wraps it. */
  scrimClassName?: string
  label?: string
  as?: 'section' | 'aside'
  style?: CSSProperties
  /** Called when the scrim (outside the dialog) is pressed. Escape is handled by the owner. */
  onClose?: () => void
  children: ReactNode
}

/**
 * Scrim + dialog with a focus trap: focus moves into the dialog on open, Tab and Shift+Tab
 * cycle inside it, and focus returns to the element that opened it on close.
 */
export default function Modal({ className = '', scrimClassName = '', label, as = 'section', style, onClose, children }: ModalProps) {
  const dialog = useRef<HTMLElement>(null)

  useEffect(() => {
    const node = dialog.current
    if (!node) return
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    node.focus({ preventScroll: true })
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return
      const items = [...node.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(item => item.offsetParent !== null || item === document.activeElement)
      if (!items.length) { event.preventDefault(); return }
      const first = items[0], last = items[items.length - 1]
      if (event.shiftKey && (document.activeElement === first || document.activeElement === node)) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    node.addEventListener('keydown', onKeyDown)
    return () => {
      node.removeEventListener('keydown', onKeyDown)
      if (opener && document.contains(opener)) opener.focus({ preventScroll: true })
    }
  }, [])

  return (
    <div className={`modal-scrim ${scrimClassName}`.trim()} onMouseDown={event => { if (onClose && event.target === event.currentTarget) onClose() }}>
      {createElement(as, { ref: dialog, className, style, role: 'dialog', 'aria-modal': true, 'aria-label': label, tabIndex: -1 }, children)}
    </div>
  )
}
