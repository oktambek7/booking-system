import { useEffect, useState, type FormEvent } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { KeyRound, ShieldCheck, ShieldOff } from 'lucide-react'
import { apiFetch, setAccessToken } from './session'

type Lang = 'uz' | 'en' | 'ru'
type Status = { enabled: boolean; recovery_codes_left: number; required: boolean }
type Step = 'idle' | 'password' | 'scan' | 'codes' | 'disable' | 'regenerate'

const text: Record<Lang, Record<string, string>> = {
  uz: { title: 'Ikki bosqichli tasdiqlash', off: 'Yoqilmagan. Kirishda parolga qo‘shimcha ravishda autentifikator ilovasidagi kod so‘raladi.', on: 'Yoqilgan.', left: 'ta zaxira kod qoldi', required: 'Operator hisoblari uchun majburiy.', enable: 'Yoqish', password: 'Parol', continue: 'Davom etish', scan: 'Autentifikator ilovasida (Google Authenticator, Authy, 1Password…) QR kodni skanerlang yoki kalitni qo‘lda kiriting, so‘ng ilovadagi 6 xonali kodni kiriting.', key: 'Kalit', code: 'Kod', confirm: 'Tasdiqlash', codesTitle: 'Zaxira kodlar', codesHint: 'Telefoningizni yo‘qotsangiz, har bir kod bir marta kirishga yordam beradi. Ularni hozir saqlang: boshqa ko‘rsatilmaydi.', done: 'Saqladim', disable: 'O‘chirish', disableHint: 'Parolingiz va joriy kod (yoki zaxira kod) kerak. Barcha qurilmalardan chiqarilasiz.', regenerate: 'Yangi zaxira kodlar', cancel: 'Bekor qilish', failed: 'Amalga oshmadi.' },
  en: { title: 'Two-step verification', off: 'Off. When on, signing in asks for a code from an authenticator app as well as your password.', on: 'On.', left: 'recovery codes left', required: 'Required for operator accounts.', enable: 'Turn on', password: 'Password', continue: 'Continue', scan: 'In your authenticator app (Google Authenticator, Authy, 1Password…) scan the QR code or type the key, then enter the 6-digit code it shows.', key: 'Key', code: 'Code', confirm: 'Confirm', codesTitle: 'Recovery codes', codesHint: 'If you lose your phone, each code signs you in once. Save them now: they are not shown again.', done: 'I saved them', disable: 'Turn off', disableHint: 'Needs your password and a current code (or a recovery code). You will be signed out everywhere.', regenerate: 'New recovery codes', cancel: 'Cancel', failed: 'That did not work.' },
  ru: { title: 'Двухэтапная проверка', off: 'Выключена. Если включить, при входе кроме пароля нужен код из приложения-аутентификатора.', on: 'Включена.', left: 'резервных кодов осталось', required: 'Обязательна для аккаунтов операторов.', enable: 'Включить', password: 'Пароль', continue: 'Продолжить', scan: 'В приложении-аутентификаторе (Google Authenticator, Authy, 1Password…) отсканируйте QR-код или введите ключ, затем введите 6-значный код.', key: 'Ключ', code: 'Код', confirm: 'Подтвердить', codesTitle: 'Резервные коды', codesHint: 'Если потеряете телефон, каждый код позволит войти один раз. Сохраните их сейчас: повторно они не показываются.', done: 'Я сохранил', disable: 'Выключить', disableHint: 'Нужны пароль и текущий код (или резервный). Вы выйдете со всех устройств.', regenerate: 'Новые резервные коды', cancel: 'Отмена', failed: 'Не получилось.' },
}

/** Turn two-step verification on or off, and manage recovery codes. Lives in the profile panel. */
export default function TwoFactorSection({ api, token, lang, onSignedOut }: { api: string; token: string; lang: Lang; onSignedOut: () => void }) {
  const t = (key: string) => text[lang][key]
  const [status, setStatus] = useState<Status | null>(null)
  const [step, setStep] = useState<Step>('idle')
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [codes, setCodes] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }

  async function load() {
    const response = await apiFetch(`${api}/api/auth/2fa`, { headers })
    if (response.ok) setStatus(await response.json())
  }
  useEffect(() => { void load() }, [token === ''])

  async function call(path: string, body: unknown): Promise<Response | null> {
    setBusy(true); setError('')
    try {
      const response = await apiFetch(`${api}${path}`, { method: 'POST', headers, body: JSON.stringify(body) })
      if (!response.ok && response.status !== 204) throw new Error((await response.json().catch(() => ({}))).detail || t('failed'))
      return response
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('failed')); return null }
    finally { setBusy(false) }
  }
  const field = (event: FormEvent<HTMLFormElement>, name: string) => String(new FormData(event.currentTarget).get(name) ?? '')

  async function begin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const response = await call('/api/auth/2fa/setup', { password: field(event, 'password') })
    if (response) { setSetup(await response.json()); setStep('scan') }
  }
  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const response = await call('/api/auth/2fa/enable', { code: field(event, 'code') })
    if (!response) return
    const data = await response.json()
    setAccessToken(data.access_token, data.expires_in)       // enabling ended the other sessions; this one continues
    setCodes(data.recovery_codes); setSetup(null); setStep('codes'); void load()
  }
  async function disable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const response = await call('/api/auth/2fa/disable', { password: field(event, 'password'), code: field(event, 'code') })
    if (response) onSignedOut()
  }
  async function regenerate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const response = await call('/api/auth/2fa/recovery-codes', { password: field(event, 'password'), code: field(event, 'code') })
    if (response) { setCodes((await response.json()).recovery_codes); setStep('codes'); void load() }
  }
  const cancel = () => { setStep('idle'); setSetup(null); setError('') }

  if (!status) return null
  return (
    <section className="profile-privacy" aria-label={t('title')}>
      <h3>{t('title')}</h3>
      <p>{status.enabled ? `${t('on')} ${status.recovery_codes_left} ${t('left')}.` : t('off')}{status.required ? ` ${t('required')}` : ''}</p>

      {step === 'idle' && !status.enabled && <button type="button" className="profile-telegram-button" onClick={() => setStep('password')}><ShieldCheck size={15} /> {t('enable')}</button>}
      {step === 'idle' && status.enabled && <div className="profile-privacy-actions">
        <button type="button" className="profile-telegram-button" onClick={() => setStep('regenerate')}><KeyRound size={15} /> {t('regenerate')}</button>
        {!status.required && <button type="button" className="profile-privacy-danger" onClick={() => setStep('disable')}><ShieldOff size={15} /> {t('disable')}</button>}
      </div>}

      {step === 'password' && <form className="profile-privacy-delete" onSubmit={event => void begin(event)}>
        <label>{t('password')}<input name="password" type="password" autoComplete="current-password" required /></label>
        <div className="profile-privacy-actions"><button className="profile-telegram-button" disabled={busy}>{t('continue')}</button><button type="button" className="profile-telegram-button" onClick={cancel}>{t('cancel')}</button></div>
      </form>}

      {step === 'scan' && setup && <form className="profile-privacy-delete" onSubmit={event => void confirm(event)}>
        <p>{t('scan')}</p>
        <div className="twofactor-qr"><QRCodeSVG value={setup.otpauth_uri} size={168} level="M" includeMargin /></div>
        <p className="twofactor-key">{t('key')}: <code>{setup.secret}</code></p>
        <label>{t('code')}<input name="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,7}" required /></label>
        <div className="profile-privacy-actions"><button className="profile-telegram-button" disabled={busy}>{t('confirm')}</button><button type="button" className="profile-telegram-button" onClick={cancel}>{t('cancel')}</button></div>
      </form>}

      {step === 'codes' && <div className="profile-privacy-delete">
        <h4>{t('codesTitle')}</h4>
        <p>{t('codesHint')}</p>
        <ul className="twofactor-codes">{codes.map(code => <li key={code}><code>{code}</code></li>)}</ul>
        <button type="button" className="profile-telegram-button" onClick={() => { setCodes([]); setStep('idle') }}>{t('done')}</button>
      </div>}

      {(step === 'disable' || step === 'regenerate') && <form className="profile-privacy-delete" onSubmit={event => void (step === 'disable' ? disable(event) : regenerate(event))}>
        {step === 'disable' && <p>{t('disableHint')}</p>}
        <label>{t('password')}<input name="password" type="password" autoComplete="current-password" required /></label>
        <label>{t('code')}<input name="code" autoComplete="one-time-code" required /></label>
        <div className="profile-privacy-actions">
          <button className={step === 'disable' ? 'profile-privacy-danger' : 'profile-telegram-button'} disabled={busy}>{step === 'disable' ? t('disable') : t('regenerate')}</button>
          <button type="button" className="profile-telegram-button" onClick={cancel}>{t('cancel')}</button>
        </div>
      </form>}
      {error && <p className="dialog-error" role="alert">{error}</p>}
    </section>
  )
}
