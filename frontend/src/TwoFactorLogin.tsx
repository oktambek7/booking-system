import type { FormEvent } from 'react'

type Lang = 'uz' | 'en' | 'ru'

const text: Record<Lang, Record<string, string>> = {
  uz: { title: 'Ikki bosqichli tasdiqlash', hint: 'Autentifikator ilovasidagi 6 xonali kodni kiriting. Telefon yo‘q bo‘lsa, zaxira kodlardan birini kiriting.', code: 'Kod', submit: 'Kirish', back: 'Orqaga' },
  en: { title: 'Two-step verification', hint: 'Enter the 6-digit code from your authenticator app, or one of your recovery codes if you do not have your phone.', code: 'Code', submit: 'Sign in', back: 'Back' },
  ru: { title: 'Двухэтапная проверка', hint: 'Введите 6-значный код из приложения-аутентификатора или один из резервных кодов, если телефона нет.', code: 'Код', submit: 'Войти', back: 'Назад' },
}

export function twoFactorTitle(lang: Lang) { return text[lang].title }

/** The second sign-in step: shown after the password was accepted for an account with two-step verification. */
export default function TwoFactorLogin({ lang, busy, error, onSubmit, onBack }: { lang: Lang; busy: boolean; error: string; onSubmit: (code: string) => void; onBack: () => void }) {
  const t = (key: string) => text[lang][key]
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSubmit(String(new FormData(event.currentTarget).get('code') ?? '').trim())
  }
  return (
    <>
      <p>{t('hint')}</p>
      <form onSubmit={submit}>
        <label>{t('code')}<input name="code" autoFocus autoComplete="one-time-code" required maxLength={20} /></label>
        {error && <p className="dialog-error" role="alert">{error}</p>}
        <button className="button-primary auth-submit" disabled={busy}>{busy ? '…' : t('submit')}</button>
      </form>
      <button className="auth-switch" onClick={onBack}>{t('back')}</button>
    </>
  )
}
