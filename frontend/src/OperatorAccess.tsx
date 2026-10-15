import { useEffect, useState, type FormEvent } from 'react'
import { CheckCircle2, LoaderCircle, ShieldCheck, UserMinus, UserPlus } from 'lucide-react'
import { apiFetch } from './session'

type Operator = { user_id: number; email: string; nickname: string; active: boolean; owner: boolean; cinemas: string[] }

function headers(token: string) { return { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } }

/** Owner-only: who is an operator, and which cinemas each may manage. */
export default function OperatorAccess({ api, token, cinemaNames }: { api: string; token: string; cinemaNames: string[] }) {
  const [operators, setOperators] = useState<Operator[] | null>(null)
  const [scope, setScope] = useState<'owner' | 'cinemas'>('cinemas')
  const [picked, setPicked] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  async function load() {
    const response = await apiFetch(`${api}/api/admin/operators`, { headers: headers(token) })
    if (response.ok) setOperators(await response.json())
    else setError((await response.json().catch(() => ({}))).detail || 'Operatorlar ro‘yxati yuklanmadi.')
  }
  useEffect(() => { void load() }, [])

  async function call(request: () => Promise<Response>, success: string) {
    setBusy(true); setError(''); setNotice('')
    try {
      const response = await request()
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Saqlab bo‘lmadi.')
      setNotice(success)
      await load()
      return true
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Saqlab bo‘lmadi.'); return false }
    finally { setBusy(false) }
  }

  async function grant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const email = String(new FormData(form).get('email') || '').trim()
    const ok = await call(() => apiFetch(`${api}/api/admin/operators`, { method: 'PUT', headers: headers(token),
      body: JSON.stringify({ email, cinemas: scope === 'owner' ? null : picked }) }), 'Operator huquqi saqlandi.')
    if (ok) form.reset()
  }

  async function revoke(operator: Operator) {
    if (!window.confirm(`${operator.email} operator huquqidan mahrum qilinsinmi? Ular barcha qurilmalardan chiqarib yuboriladi.`)) return
    await call(() => apiFetch(`${api}/api/admin/operators/${operator.user_id}`, { method: 'DELETE', headers: headers(token) }), 'Operator huquqi olib tashlandi.')
  }

  const toggle = (name: string) => setPicked(current => current.includes(name) ? current.filter(item => item !== name) : [...current, name])

  return <div className="operator-two-column">
    <section className="operator-section">
      <div className="operator-section-head"><div><h2>Operator qo‘shish</h2></div></div>
      {notice && <p className="operator-alert operator-success"><CheckCircle2 size={16} />{notice}</p>}
      {error && <p className="operator-alert operator-error">{error}</p>}
      <form className="operator-form" onSubmit={event => void grant(event)}>
        <label>Hisob e-pochtasi<input name="email" type="email" required placeholder="operator@example.com" /></label>
        <fieldset className="operator-scope">
          <legend>Kirish huquqi</legend>
          <label><input type="radio" name="scope" checked={scope === 'cinemas'} onChange={() => setScope('cinemas')} /> Faqat tanlangan kinoteatrlar</label>
          {scope === 'cinemas' && <div className="operator-scope-list">{cinemaNames.map(name => <label key={name}><input type="checkbox" checked={picked.includes(name)} onChange={() => toggle(name)} /> {name}</label>)}</div>}
          <label><input type="radio" name="scope" checked={scope === 'owner'} onChange={() => setScope('owner')} /> Egasi: barcha kinoteatrlar, filmlar, promolar va operatorlar</label>
        </fieldset>
        <p className="operator-help">Hisob mavjud va e-pochtasi tasdiqlangan bo‘lishi kerak. O‘zingizning huquqingizni o‘zgartira olmaysiz.</p>
        <button className="operator-primary" disabled={busy || (scope === 'cinemas' && !picked.length)}><UserPlus size={16} />Saqlash</button>
      </form>
    </section>
    <section className="operator-section">
      <div className="operator-section-head"><div><h2>Operatorlar</h2></div><b>{operators?.length ?? 0} ta</b></div>
      {operators === null ? <div className="operator-loading"><LoaderCircle size={20} /></div> : <div className="operator-hall-list">{operators.map(operator => <article className="operator-hall" key={operator.user_id}>
        <span><ShieldCheck size={19} /></span>
        <div><b>{operator.nickname}</b><small>{operator.email}</small><em>{operator.owner ? 'EGASI · hamma narsa' : operator.cinemas.length ? operator.cinemas.join(', ') : 'kinoteatr biriktirilmagan'}</em></div>
        <button onClick={() => void revoke(operator)} disabled={busy}><UserMinus size={14} /> Olib tashlash</button>
      </article>)}</div>}
    </section>
  </div>
}
