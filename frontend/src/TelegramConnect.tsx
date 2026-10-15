import { useCallback, useEffect, useState } from 'react'
import { Send } from 'lucide-react'
import { apiFetch } from './session'

type Lang = 'uz' | 'en' | 'ru'
type Status = { configured: boolean; bot_username: string | null; linked: boolean }

const text: Record<Lang, Record<string, string>> = {
  uz: { title: 'Telegram xabarnomalari', hint: 'Chipta tasdig‘i, eslatmalar va pul qaytarish haqida Telegramda ham xabar oling.', connect: 'Telegramni ulash', waiting: 'Telegramda “Start” tugmasini bosing…', open: 'Telegramni ochish', connected: 'Telegram ulangan', disconnect: 'Uzish', failed: 'Telegram ulanmadi. Qayta urinib ko‘ring.' },
  en: { title: 'Telegram notifications', hint: 'Also get ticket confirmations, reminders and refunds in Telegram.', connect: 'Connect Telegram', waiting: 'Press “Start” in Telegram…', open: 'Open Telegram', connected: 'Telegram connected', disconnect: 'Disconnect', failed: 'Could not connect Telegram. Please try again.' },
  ru: { title: 'Уведомления в Telegram', hint: 'Получайте подтверждения билетов, напоминания и возвраты ещё и в Telegram.', connect: 'Подключить Telegram', waiting: 'Нажмите «Start» в Telegram…', open: 'Открыть Telegram', connected: 'Telegram подключён', disconnect: 'Отключить', failed: 'Не удалось подключить Telegram. Попробуйте ещё раз.' },
}

/** Connect or disconnect the customer's Telegram chat. Renders nothing when the deployment has no bot configured. */
export default function TelegramConnect({ api, token, lang }: { api: string; token: string; lang: Lang }) {
  const t = (key: string) => text[lang][key]
  const [status, setStatus] = useState<Status | null>(null)
  const [waiting, setWaiting] = useState(false)
  const [link, setLink] = useState('')
  const [error, setError] = useState('')
  const headers = { Authorization: `Bearer ${token}` }

  const load = useCallback(async () => {
    try {
      const response = await apiFetch(`${api}/api/telegram`, { headers: { Authorization: `Bearer ${token}` } })
      if (!response.ok) return
      const next = await response.json() as Status
      setStatus(next)
      if (next.linked) { setWaiting(false); setLink('') }
    } catch { /* a network blip: keep showing what we had */ }
  }, [api, token])

  useEffect(() => { void load() }, [load])

  useEffect(() => {      // after the link is opened, check every few seconds for up to two minutes
    if (!waiting) return undefined
    const poll = setInterval(() => void load(), 3000)
    const giveUp = setTimeout(() => setWaiting(false), 120_000)
    return () => { clearInterval(poll); clearTimeout(giveUp) }
  }, [waiting, load])

  if (!status?.configured) return null

  async function connect() {
    setError('')
    const tab = window.open('', '_blank')       // opened now, inside the click, so popup blockers allow it
    if (tab) tab.opener = null
    try {
      const response = await apiFetch(`${api}/api/telegram/link`, { method: 'POST', headers })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || t('failed'))
      setLink(data.url)
      setWaiting(true)
      if (tab) tab.location.href = data.url
    } catch (cause) {
      tab?.close()
      setError(cause instanceof Error ? cause.message : t('failed'))
    }
  }

  async function disconnect() {
    setError('')
    try {
      const response = await apiFetch(`${api}/api/telegram/link`, { method: 'DELETE', headers })
      if (!response.ok && response.status !== 204) throw new Error(t('failed'))
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('failed')) }
  }

  return (
    <section className="profile-telegram" aria-label={t('title')}>
      <h3><Send size={16} /> {t('title')}</h3>
      {status.linked ? (
        <div className="profile-telegram-row"><span className="profile-telegram-ok">{t('connected')}</span>
          <button type="button" className="profile-telegram-button" onClick={() => void disconnect()}>{t('disconnect')}</button></div>
      ) : (
        <>
          <p>{t('hint')}</p>
          {waiting && <p role="status">{t('waiting')} {link && <a href={link} target="_blank" rel="noopener noreferrer">{t('open')}</a>}</p>}
          {!waiting && <button type="button" className="profile-telegram-button" onClick={() => void connect()}>{t('connect')}</button>}
        </>
      )}
      {error && <p className="dialog-error" role="alert">{error}</p>}
    </section>
  )
}
