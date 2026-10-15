import { useState, type FormEvent } from 'react'
import { Download, Trash2 } from 'lucide-react'
import { apiFetch } from './session'

type Lang = 'uz' | 'en' | 'ru'

const text: Record<Lang, Record<string, string>> = {
  uz: { title: 'Maxfiylik va ma‘lumotlar', export: 'Ma‘lumotlarimni yuklab olish', exportHint: 'Hisobingizdagi barcha ma‘lumotlar nusxasi (JSON fayl).', remove: 'Hisobni o‘chirish', removeHint: 'Shaxsiy ma‘lumotlaringiz o‘chiriladi. To‘lov yozuvlari qonun talabiga ko‘ra ismsiz saqlanadi. Bu amalni qaytarib bo‘lmaydi.', password: 'Parolingiz', understand: 'Bu amalni qaytarib bo‘lmasligini tushundim', confirm: 'Hisobni butunlay o‘chirish', cancel: 'Bekor qilish', failed: 'Amalni bajarib bo‘lmadi. Qayta urinib ko‘ring.' },
  en: { title: 'Privacy and data', export: 'Download my data', exportHint: 'A copy of everything your account holds (a JSON file).', remove: 'Delete my account', removeHint: 'Your personal details are erased. Payment records are kept without your name, as the law requires. This cannot be undone.', password: 'Your password', understand: 'I understand this cannot be undone', confirm: 'Delete my account permanently', cancel: 'Cancel', failed: 'That did not work. Please try again.' },
  ru: { title: 'Конфиденциальность и данные', export: 'Скачать мои данные', exportHint: 'Копия всего, что хранится в вашем аккаунте (файл JSON).', remove: 'Удалить аккаунт', removeHint: 'Ваши личные данные будут стёрты. Записи о платежах хранятся без имени, как того требует закон. Это действие нельзя отменить.', password: 'Ваш пароль', understand: 'Я понимаю, что это нельзя отменить', confirm: 'Удалить аккаунт навсегда', cancel: 'Отмена', failed: 'Не получилось. Попробуйте ещё раз.' },
}

/** Download a copy of the customer's data, or close the account (password and an explicit acknowledgement required). */
export default function PrivacySection({ api, token, lang, onDeleted }: { api: string; token: string; lang: Lang; onDeleted: () => void }) {
  const t = (key: string) => text[lang][key]
  const [removing, setRemoving] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const headers = { Authorization: `Bearer ${token}` }

  async function download() {
    setBusy(true); setError('')
    try {
      const response = await apiFetch(`${api}/api/account/export`, { headers })
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || t('failed'))
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = (/filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '') ?? [])[1] ?? 'parda-data.json'
      document.body.append(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 10_000)
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('failed')) }
    finally { setBusy(false) }
  }

  async function remove(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setBusy(true); setError('')
    try {
      const response = await apiFetch(`${api}/api/account`, {
        method: 'DELETE', headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: String(form.get('password') ?? ''), confirm: form.get('understand') === 'on' }),
      })
      if (response.status !== 204) throw new Error((await response.json().catch(() => ({}))).detail || t('failed'))
      onDeleted()
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('failed')); setBusy(false) }
  }

  return (
    <section className="profile-privacy" aria-label={t('title')}>
      <h3>{t('title')}</h3>
      <p>{t('exportHint')}</p>
      <button type="button" className="profile-telegram-button" disabled={busy} onClick={() => void download()}><Download size={15} /> {t('export')}</button>
      {removing ? (
        <form className="profile-privacy-delete" onSubmit={event => void remove(event)}>
          <p>{t('removeHint')}</p>
          <label>{t('password')}<input name="password" type="password" autoComplete="current-password" required /></label>
          <label className="profile-privacy-check"><input name="understand" type="checkbox" required /> {t('understand')}</label>
          <div className="profile-privacy-actions">
            <button className="profile-privacy-danger" disabled={busy}><Trash2 size={15} /> {t('confirm')}</button>
            <button type="button" className="profile-telegram-button" disabled={busy} onClick={() => { setRemoving(false); setError('') }}>{t('cancel')}</button>
          </div>
        </form>
      ) : (
        <button type="button" className="profile-privacy-danger" onClick={() => setRemoving(true)}><Trash2 size={15} /> {t('remove')}</button>
      )}
      {error && <p className="dialog-error" role="alert">{error}</p>}
    </section>
  )
}
