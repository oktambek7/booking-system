import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { Armchair, CalendarDays, CheckCircle2, CircleDollarSign, Clapperboard, DoorOpen, Film, LayoutDashboard, LoaderCircle, Plus, RefreshCw, ScanLine, Ticket, Users, X } from 'lucide-react'
import { calendarDate, formatDateTime, isoDateInTashkent } from './dateFormat'

type Movie = { id:number; title:string; active:boolean; catalog_status?:string; duration_minutes?:number|null; language:string; age_rating:string; poster_url:string }
type Hall = { id:number; name:string; cinema_name:string; city:string; address:string; hall_type:'standard'|'vip'; formats:string[]; seat_count:number; active?:boolean; source_name?:string|null }
type Booking = { id:number; status:'pending'|'confirmed'|'cancelled'|'completed'; seat_count:number; total_price:number|string; ticket_code:string|null; checked_in_at:string|null; movie_title:string; starts_at:string; cinema_name:string; auditorium_name:string; seats:string[]; customer_nickname:string; customer_email:string }
type Screening = { id:number; movie_id:number; auditorium_id:number; starts_at:string; ends_at:string; base_price:number|string; premium_surcharge:number|string; movie_title:string; cinema_name:string; auditorium_name:string; format_type:string; hall_type:'standard'|'vip'; available_seats:number; booking_count:number; seats_sold:number; confirmed_revenue:number|string }
type Dashboard = { metrics:{date:string; screenings:number; upcoming_screenings:number; bookings:number; confirmed_bookings:number; pending_bookings:number; seats_sold:number; seats_available:number; confirmed_revenue:number|string}; screenings:Screening[]; bookings:Booking[] }
type Promotion = {id:number; code:string; label:string; percent_off:number; min_order_amount:number|string; max_discount_amount:number|string|null; usage_limit:number|null; usage_count:number; starts_at:string|null; ends_at:string|null; active:boolean}

const number = new Intl.NumberFormat('uz-UZ')
const money = (value:number|string) => `${number.format(Number(value))} so‘m`
const dateKey = (value = new Date()) => isoDateInTashkent(value)

function headers(token:string) { return { Authorization:`Bearer ${token}`, 'Content-Type':'application/json' } }
function isoFromForm(day:string, value:string) { return new Date(`${day}T${value}:00+05:00`).toISOString() }

export default function OperatorDashboard({ api, token, onClose }: { api:string; token:string; onClose:()=>void }) {
  const [tab, setTab] = useState<'overview'|'schedule'|'halls'|'catalog'|'tickets'|'promotions'>('overview')
  const [day, setDay] = useState(dateKey())
  const [dashboard, setDashboard] = useState<Dashboard|null>(null)
  const [movies, setMovies] = useState<Movie[]>([])
  const [halls, setHalls] = useState<Hall[]>([])
  const [promotions, setPromotions] = useState<Promotion[]>([])
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const visibleMovies = useMemo(() => movies.filter(movie => movie.active && movie.catalog_status !== 'upcoming' && movie.duration_minutes), [movies])
  const activeHalls = useMemo(() => halls.filter(hall => hall.active !== false), [halls])

  async function load() {
    setLoading(true); setError('')
    try {
      const [dashboardResult, moviesResult, hallsResult, promotionsResult] = await Promise.all([
        fetch(`${api}/api/admin/dashboard?date=${day}`, { headers:headers(token) }),
        fetch(`${api}/api/movies`, { headers:headers(token) }),
        fetch(`${api}/api/admin/cinemas`, { headers:headers(token) }),
        fetch(`${api}/api/admin/promotions`, { headers:headers(token) }),
      ])
      const payload = await dashboardResult.json()
      if (!dashboardResult.ok) throw new Error(payload.detail || 'Boshqaruv ma’lumotlari yuklanmadi.')
      setDashboard(payload)
      if (moviesResult.ok) setMovies(await moviesResult.json())
      if (hallsResult.ok) setHalls(await hallsResult.json())
      if (promotionsResult.ok) setPromotions(await promotionsResult.json())
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Boshqaruv ma’lumotlari yuklanmadi.')
    } finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [day])

  async function submit(event:FormEvent<HTMLFormElement>, path:string, body:unknown, success:string) {
    event.preventDefault(); const form = event.currentTarget; setBusy(true); setNotice(''); setError('')
    try {
      const result = await fetch(`${api}${path}`, { method:'POST', headers:headers(token), body:JSON.stringify(body) })
      const data = await result.json()
      if (!result.ok) throw new Error(data.detail || 'Saqlab bo‘lmadi.')
      setNotice(success); form.reset(); await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Saqlab bo‘lmadi.') }
    finally { setBusy(false) }
  }
  async function updateBooking(booking:Booking, status:'cancelled'|'completed') {
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await fetch(`${api}/api/bookings/${booking.id}/status`, { method:'PATCH', headers:headers(token), body:JSON.stringify({ status }) })
      const data = await result.json()
      if (!result.ok) throw new Error(data.detail || 'Chipta holati yangilanmadi.')
      setNotice(status === 'completed' ? 'Seans yakunlangan deb belgilandi.' : 'Buyurtma bekor qilindi va joylar bo‘shatildi.')
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Chipta holati yangilanmadi.') }
    finally { setBusy(false) }
  }
  async function checkIn(event:FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const ticketCode = String(new FormData(form).get('ticket_code') || '').trim()
    if (!ticketCode) return
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await fetch(`${api}/api/admin/tickets/check-in`, { method:'POST', headers:headers(token), body:JSON.stringify({ ticket_code:ticketCode }) })
      const data = await result.json()
      if (!result.ok) throw new Error(data.detail || 'Chipta tekshirilmadi.')
      setNotice(`${data.booking.movie_title} · ${data.booking.seats.join(', ')} uchun kirish tasdiqlandi.`)
      form.reset(); await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Chipta tekshirilmadi.') }
    finally { setBusy(false) }
  }
  async function toggleHall(hall:Hall) {
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await fetch(`${api}/api/cinemas/${hall.id}`, { method:'PATCH', headers:headers(token), body:JSON.stringify({ active:hall.active === false }) })
      const data = await result.json()
      if (!result.ok) throw new Error(data.detail || 'Zal holati yangilanmadi.')
      setNotice(hall.active === false ? 'Zal qayta ochildi.' : 'Zal yangi seanslar uchun yopildi.')
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Zal holati yangilanmadi.') }
    finally { setBusy(false) }
  }
  async function syncCatalog() {
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await fetch(`${api}/api/catalog/sync`, { method:'POST', headers:headers(token) })
      const data = await result.json()
      if (!result.ok) throw new Error(data.detail || 'TMDB katalogini yangilab bo‘lmadi.')
      setNotice(`${data.imported_now_playing} namoyishdagi va ${data.imported_upcoming} yaqin premyera yangilandi.`)
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'TMDB katalogini yangilab bo‘lmadi.') }
    finally { setBusy(false) }
  }
  const nav = [
    ['overview', 'Umumiy', LayoutDashboard], ['schedule', 'Seanslar', CalendarDays], ['halls', 'Zallar', DoorOpen], ['catalog', 'Filmlar', Film], ['tickets', 'Chiptalar', Ticket], ['promotions', 'Promolar', CircleDollarSign],
  ] as const
  const selected = nav.find(item => item[0] === tab)?.[1]

  return <div className="operator-scrim" role="presentation">
    <section className="operator-shell" aria-label="Parda cinema operator dashboard">
      <header className="operator-header">
        <div className="operator-title"><span className="operator-title-mark"><img src="/parda-logo-mark.jpg" alt=""/></span><div><span className="operator-eyebrow">PARDA · OPERATOR</span><h1>{selected}</h1></div></div>
        <div className="operator-header-actions"><button className="operator-refresh" onClick={() => void load()} disabled={loading || busy}><RefreshCw size={16}/>Yangilash</button><button className="operator-close" onClick={onClose} aria-label="Boshqaruvni yopish"><X size={19}/></button></div>
      </header>
      <div className="operator-layout">
        <aside className="operator-sidebar"><div className="operator-brand"><img src="/parda-logo-mark.jpg" alt=""/><span>PARDA</span></div><nav>{nav.map(([key,label,Icon]) => <button key={key} className={tab === key ? 'operator-nav-active' : ''} onClick={() => setTab(key)}><Icon size={17}/><span>{label}</span></button>)}</nav><small>Asia/Tashkent<br/>Operator workspace</small></aside>
        <main className="operator-content">
          <div className="operator-toolbar"><label>Sana<input type="date" value={day} min={dateKey()} onChange={event => setDay(event.target.value)}/></label><span>{calendarDate(day, 'uz')}</span></div>
          {notice && <p className="operator-alert operator-success"><CheckCircle2 size={16}/>{notice}</p>}
          {error && <p className="operator-alert operator-error">{error}</p>}
          {loading ? <div className="operator-loading"><LoaderCircle size={24}/><span>Operator ma’lumotlari yuklanmoqda…</span></div> : <>
            {tab === 'overview' && <Overview dashboard={dashboard} busy={busy} onUpdate={updateBooking}/>} 
            {tab === 'schedule' && <Schedule dashboard={dashboard} movies={visibleMovies} halls={activeHalls} day={day} busy={busy} onSubmit={submit}/>} 
            {tab === 'halls' && <Halls halls={halls} busy={busy} onSubmit={submit} onToggle={toggleHall}/>} 
            {tab === 'catalog' && <Catalog movies={movies} busy={busy} onSubmit={submit} onSync={syncCatalog}/>} 
            {tab === 'tickets' && <Tickets bookings={dashboard?.bookings || []} busy={busy} onUpdate={updateBooking} onCheckIn={checkIn}/>} 
            {tab === 'promotions' && <Promotions promotions={promotions} busy={busy} onSubmit={submit}/>}
          </>}
        </main>
      </div>
    </section>
  </div>
}

function Overview({ dashboard, busy, onUpdate }: { dashboard:Dashboard|null; busy:boolean; onUpdate:(booking:Booking,status:'cancelled'|'completed')=>Promise<void> }) {
  if (!dashboard) return null
  const { metrics, screenings, bookings } = dashboard
  const cards = [
    ['Bugungi seanslar', metrics.screenings, `${metrics.upcoming_screenings} tasi hali boshlanmagan`, Clapperboard],
    ['Sotilgan joylar', metrics.seats_sold, `${metrics.seats_available} ta bo‘sh joy`, Users],
    ['Tasdiqlangan chipta', metrics.confirmed_bookings, `${metrics.pending_bookings} ta kutilmoqda`, Ticket],
    ['Tasdiqlangan tushum', money(metrics.confirmed_revenue), 'Faqat confirmed / completed', CircleDollarSign],
  ] as const
  return <>
    <section className="operator-metrics">{cards.map(([label,value,detail,Icon]) => <article key={label}><span><Icon size={18}/></span><p>{label}</p><strong>{value}</strong><small>{detail}</small></article>)}</section>
    <section className="operator-section"><div className="operator-section-head"><div><span>OPERATSIYA</span><h2>Bugungi seanslar</h2></div><b>{screenings.length} seans</b></div>{screenings.length ? <div className="operator-show-list">{screenings.map(item => <ScreeningRow key={item.id} item={item}/>)}</div> : <Empty icon={<CalendarDays/>} title="Bu sana uchun seans yo‘q" text="Seanslar bo‘limidan film, zal va vaqtni tanlab yangi seans yarating."/>}</section>
    <section className="operator-section operator-recent"><div className="operator-section-head"><div><span>YANGI BUYURTMALAR</span><h2>Chipta harakati</h2></div><b>{bookings.length} buyurtma</b></div>{bookings.length ? <div className="operator-ticket-table">{bookings.slice(0, 6).map(item => <TicketRow key={item.id} booking={item} actions onUpdate={onUpdate} busy={busy}/>)}</div> : <Empty icon={<Ticket/>} title="Hali buyurtma yo‘q" text="Yangi xaridlar shu yerda ko‘rinadi."/>}</section>
  </>
}

function ScreeningRow({ item }: { item:Screening }) {
  const total = item.seats_sold + item.available_seats
  const fill = total ? Math.min(100, Math.round((item.seats_sold / total) * 100)) : 0
  return <article className="operator-show"><div className="operator-show-time"><b>{new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Tashkent',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(item.starts_at))}</b><span>{item.format_type}</span></div><div className="operator-show-info"><b>{item.movie_title}</b><small>{item.cinema_name} · {item.auditorium_name} · {item.hall_type === 'vip' ? 'VIP' : 'Standard'}</small></div><div className="operator-capacity"><div><span>Bandlik</span><b>{item.seats_sold}/{total || 0}</b></div><i><em style={{width:`${fill}%`}}/></i></div><div className="operator-show-revenue"><b>{money(item.confirmed_revenue)}</b><small>{item.booking_count} buyurtma</small></div></article>
}

function Schedule({ dashboard, movies, halls, day, busy, onSubmit }: { dashboard:Dashboard|null; movies:Movie[]; halls:Hall[]; day:string; busy:boolean; onSubmit:(event:FormEvent<HTMLFormElement>,path:string,body:unknown,success:string)=>Promise<void> }) {
  const [hallId, setHallId] = useState('')
  const selectedHall = halls.find(hall => String(hall.id) === hallId) || halls[0]
  const formats = selectedHall?.formats?.length ? selectedHall.formats : ['2D']
  return <div className="operator-two-column"><section className="operator-section"><div className="operator-section-head"><div><span>YANGI SEANS</span><h2>Jadvalga qo‘shish</h2></div></div><form className="operator-form" onSubmit={event => { const form = new FormData(event.currentTarget); return void onSubmit(event, '/api/screenings', { movie_id:Number(form.get('movie')), auditorium_id:Number(form.get('hall')), starts_at:isoFromForm(String(form.get('date')), String(form.get('time'))), base_price:Number(form.get('price')), premium_surcharge:Number(form.get('premium')), format_type:form.get('format') }, 'Seans jadvalga qo‘shildi.') }}><label>Film<select name="movie" required disabled={!movies.length}>{movies.length ? movies.map(movie => <option key={movie.id} value={movie.id}>{movie.title}</option>) : <option>Film yo‘q</option>}</select></label><label>Zal<select name="hall" value={hallId || String(selectedHall?.id || '')} onChange={event => setHallId(event.target.value)} required disabled={!halls.length}>{halls.length ? halls.map(hall => <option key={hall.id} value={hall.id}>{hall.cinema_name} · {hall.name} ({hall.hall_type === 'vip' ? 'VIP' : 'Standard'})</option>) : <option>Zal yo‘q</option>}</select></label><div className="operator-field-row"><label>Sana<input name="date" type="date" min={dateKey()} defaultValue={day} required/></label><label>Vaqt<input name="time" type="time" defaultValue="19:00" required/></label></div><label>Format<select name="format" key={selectedHall?.id}>{formats.map(format => <option value={format} key={format}>{format}</option>)}</select></label><div className="operator-field-row"><label>Asosiy narx (UZS)<input name="price" type="number" min="0" defaultValue="35000" required/></label><label>Premium qo‘shimcha (UZS)<input name="premium" type="number" min="0" defaultValue="10000" required/></label></div><p className="operator-help">Tizim bir zalda vaqtlar ustma-ust kelishini avtomatik rad etadi.</p><button className="operator-primary" disabled={busy || !movies.length || !halls.length}><Plus size={16}/>Seans yaratish</button></form></section><section className="operator-section"><div className="operator-section-head"><div><span>{calendarDate(day, 'uz').toUpperCase()}</span><h2>Kun jadvali</h2></div><b>{dashboard?.screenings.length || 0} seans</b></div>{dashboard?.screenings.length ? <div className="operator-show-list">{dashboard.screenings.map(item => <ScreeningRow item={item} key={item.id}/>)}</div> : <Empty icon={<CalendarDays/>} title="Jadval bo‘sh" text="Bu sana uchun hali seans belgilanmagan."/>}</section></div>
}

function Halls({ halls, busy, onSubmit, onToggle }: { halls:Hall[]; busy:boolean; onSubmit:(event:FormEvent<HTMLFormElement>,path:string,body:unknown,success:string)=>Promise<void>; onToggle:(hall:Hall)=>Promise<void> }) {
  return <div className="operator-two-column"><section className="operator-section"><div className="operator-section-head"><div><span>YANGI ZAL</span><h2>Zal va o‘rindiqlar</h2></div></div><form className="operator-form" onSubmit={event => { const form = new FormData(event.currentTarget); const formats = String(form.get('formats')).split(',').map(item => item.trim().toUpperCase()).filter(item => ['2D','3D','IMAX'].includes(item)); return void onSubmit(event, '/api/cinemas', { cinema_name:form.get('cinema_name'), name:form.get('name'), city:form.get('city'), address:form.get('address'), timezone:'Asia/Tashkent', hall_type:form.get('hall_type'), row_count:Number(form.get('rows')), seats_per_row:Number(form.get('seats')), formats:formats.length ? formats : ['2D'] }, 'Zal va joylar xaritasi yaratildi.') }}><label>Kinoteatr nomi<input name="cinema_name" required placeholder="Masalan, Parda Cinema"/></label><div className="operator-field-row"><label>Zal nomi<input name="name" required placeholder="1-zal"/></label><label>Zal turi<select name="hall_type"><option value="standard">Standard</option><option value="vip">VIP</option></select></label></div><label>Manzil<input name="address" required placeholder="Ko‘cha, bino"/></label><label>Shahar<input name="city" defaultValue="Tashkent" required/></label><div className="operator-field-row"><label>Qatorlar<input name="rows" type="number" min="1" max="26" defaultValue="8" required/></label><label>Qatordagi joylar<input name="seats" type="number" min="1" max="30" defaultValue="12" required/></label></div><label>Formatlar<input name="formats" defaultValue="2D" placeholder="2D, 3D, IMAX" required/></label><p className="operator-help">Birinchi ikki qator premium joylar sifatida yaratiladi. Keyin alohida seat-map editor qo‘shish mumkin.</p><button className="operator-primary" disabled={busy}><Plus size={16}/>Zal yaratish</button></form></section><section className="operator-section"><div className="operator-section-head"><div><span>ZALLAR</span><h2>Faol inventar</h2></div><b>{halls.length} zal</b></div><div className="operator-hall-list">{halls.length ? halls.map(hall => <article key={hall.id} className={hall.active === false ? 'operator-hall operator-hall-muted' : 'operator-hall'}><span><Armchair size={19}/></span><div><b>{hall.cinema_name} · {hall.name}</b><small>{hall.address || hall.city} · {hall.seat_count} joy · {hall.formats.join(', ')}</small><em>{hall.hall_type === 'vip' ? 'VIP' : 'STANDARD'} {hall.source_name ? ` · ${hall.source_name}` : ''}</em></div><button onClick={() => void onToggle(hall)} disabled={busy}>{hall.active === false ? 'Faollashtirish' : 'Yopish'}</button></article>) : <Empty icon={<DoorOpen/>} title="Zal topilmadi" text="Birinchi kinoteatr zali va seat map’ni yarating."/>}</div></section></div>
}

function Catalog({ movies, busy, onSubmit, onSync }: { movies:Movie[]; busy:boolean; onSubmit:(event:FormEvent<HTMLFormElement>,path:string,body:unknown,success:string)=>Promise<void>; onSync:()=>Promise<void> }) {
  return <div className="operator-two-column"><section className="operator-section"><div className="operator-section-head"><div><span>QO‘LDA QO‘SHISH</span><h2>Yangi film</h2></div></div><form className="operator-form" onSubmit={event => { const form = new FormData(event.currentTarget); return void onSubmit(event, '/api/movies', { title:form.get('title'), synopsis:form.get('synopsis'), duration_minutes:Number(form.get('duration')), genre:form.get('genre'), age_rating:form.get('age_rating'), language:form.get('language'), poster_url:form.get('poster_url') }, 'Film katalogga qo‘shildi.') }}><label>Original nomi<input name="title" maxLength={180} required/></label><label>Qisqa tavsif<textarea name="synopsis" maxLength={5000}/></label><div className="operator-field-row"><label>Davomiyligi (daq.)<input name="duration" type="number" min="1" max="360" defaultValue="120" required/></label><label>Yosh cheklovi<input name="age_rating" defaultValue="13+" required/></label></div><div className="operator-field-row"><label>Janr<input name="genre" defaultValue="Drama" required/></label><label>Namoyish tili<input name="language" defaultValue="O‘zbekcha" required/></label></div><label>Poster URL<input name="poster_url" type="url" placeholder="https://…"/></label><button className="operator-primary" disabled={busy}><Plus size={16}/>Film qo‘shish</button></form></section><section className="operator-section"><div className="operator-section-head"><div><span>TMDB</span><h2>Katalog sinxronizatsiyasi</h2></div></div><div className="operator-sync-card"><Film size={28}/><div><b>Film ma’lumotlarini yangilang</b><p>Poster, original nom, yosh cheklovi, aktyorlar va yangi premyeralar TMDB’dan olinadi.</p></div><button className="operator-primary" onClick={() => void onSync()} disabled={busy}><RefreshCw size={16}/>TMDB yangilash</button></div><div className="operator-movie-list">{movies.slice(0, 12).map(movie => <article key={movie.id}>{movie.poster_url ? <img src={movie.poster_url} alt=""/> : <span><Film size={18}/></span>}<div><b>{movie.title}</b><small>{movie.language} · {movie.age_rating} · {movie.duration_minutes || '—'} daq.</small></div></article>)}</div></section></div>
}

function Promotions({ promotions, busy, onSubmit }: { promotions:Promotion[]; busy:boolean; onSubmit:(event:FormEvent<HTMLFormElement>,path:string,body:unknown,success:string)=>Promise<void> }) {
  return <div className="operator-two-column"><section className="operator-section"><div className="operator-section-head"><div><span>CHEGIRMA KAMPANIYASI</span><h2>Yangi promo kod</h2></div></div><form className="operator-form" onSubmit={event=>{const form=new FormData(event.currentTarget);const start=String(form.get('starts_at')||''),end=String(form.get('ends_at')||'');return void onSubmit(event,'/api/admin/promotions',{code:String(form.get('code')).trim().toUpperCase(),label:form.get('label'),percent_off:Number(form.get('percent_off')),min_order_amount:Number(form.get('min_order_amount')||0),max_discount_amount:form.get('max_discount_amount')?Number(form.get('max_discount_amount')):null,usage_limit:form.get('usage_limit')?Number(form.get('usage_limit')):null,starts_at:start?new Date(start).toISOString():null,ends_at:end?new Date(end).toISOString():null},'Promo kod yaratildi.')}}><label>Kod<input name="code" required maxLength={40} placeholder="WELCOME10" pattern="[A-Za-z0-9_-]+"/></label><label>Ko‘rinadigan nom<input name="label" required maxLength={120} placeholder="Yangi foydalanuvchi chegirmasi"/></label><div className="operator-field-row"><label>Chegirma (%)<input name="percent_off" type="number" min="1" max="100" defaultValue="10" required/></label><label>Foydalanish limiti<input name="usage_limit" type="number" min="1" placeholder="Cheklanmagan"/></label></div><div className="operator-field-row"><label>Minimal buyurtma<input name="min_order_amount" type="number" min="0" defaultValue="0" required/></label><label>Maks. chegirma<input name="max_discount_amount" type="number" min="0" placeholder="Cheklanmagan"/></label></div><div className="operator-field-row"><label>Boshlanishi<input name="starts_at" type="datetime-local"/></label><label>Tugashi<input name="ends_at" type="datetime-local"/></label></div><p className="operator-help">Kod checkout paytida qayta tekshiriladi. Uning limiti faqat tasdiqlangan paymentda ishlatilgan deb hisoblanadi.</p><button className="operator-primary" disabled={busy}><Plus size={16}/>Promo yaratish</button></form></section><section className="operator-section"><div className="operator-section-head"><div><span>FAOL KAMPANIYALAR</span><h2>Promo kodlar</h2></div><b>{promotions.length} ta</b></div><div className="operator-hall-list">{promotions.length?promotions.map(promo=><article className="operator-hall" key={promo.id}><span><CircleDollarSign size={19}/></span><div><b>{promo.code} · {promo.percent_off}%</b><small>{promo.label} · {money(promo.min_order_amount)} dan</small><em>{promo.usage_count}{promo.usage_limit?` / ${promo.usage_limit}`:' marta'} ishlatildi</em></div></article>):<Empty icon={<CircleDollarSign/>} title="Promo kod yo‘q" text="Checkout uchun birinchi chegirma kampaniyasini yarating."/>}</div></section></div>
}

function Tickets({ bookings, busy, onUpdate, onCheckIn }: { bookings:Booking[]; busy:boolean; onUpdate:(booking:Booking,status:'cancelled'|'completed')=>Promise<void>; onCheckIn:(event:FormEvent<HTMLFormElement>)=>Promise<void> }) {
  return <section className="operator-section"><div className="operator-section-head"><div><span>BUYURTMALAR</span><h2>Bugungi chiptalar</h2></div><b>{bookings.length} buyurtma</b></div><form className="operator-checkin" onSubmit={event=>void onCheckIn(event)}><ScanLine size={19}/><label>QR yoki chipta kodi<input name="ticket_code" required autoComplete="off" autoCapitalize="characters" maxLength={16} placeholder="PRD-XXXXXXXX"/></label><button className="operator-primary" disabled={busy}>Kirishni tasdiqlash</button><small>Faqat tasdiqlangan chipta bir marta, seansdan 2 soat oldin tekshiriladi.</small></form>{bookings.length ? <div className="operator-ticket-table">{bookings.map(booking => <TicketRow key={booking.id} booking={booking} actions onUpdate={onUpdate} busy={busy}/>)}</div> : <Empty icon={<Ticket/>} title="Bugungi chipta yo‘q" text="Tanlangan kunga tegishli buyurtmalar shu yerda chiqadi."/>}</section>
}

function TicketRow({ booking, actions, onUpdate, busy }: { booking:Booking; actions?:boolean; onUpdate?:(booking:Booking,status:'cancelled'|'completed')=>Promise<void>; busy?:boolean }) {
  const canComplete = booking.status === 'confirmed' && new Date(booking.starts_at) <= new Date()
  return <article className="operator-ticket-row"><div className="operator-ticket-person"><span className={`operator-status status-${booking.status}`}/><div><b>{booking.customer_nickname}</b><small>{booking.customer_email}</small></div></div><div><b>{booking.movie_title}</b><small>{formatDateTime(booking.starts_at, 'uz')} · {booking.auditorium_name}</small></div><div><b>{booking.seats.join(', ')}</b><small>{booking.ticket_code || money(booking.total_price)}</small></div><div className="operator-ticket-actions"><em>{booking.checked_in_at?'kiritildi':booking.status}</em>{actions && <>{canComplete && <button onClick={() => void onUpdate?.(booking, 'completed')} disabled={busy}>Yakunlash</button>}{['pending','confirmed'].includes(booking.status)&&!booking.checked_in_at && <button className="operator-danger" onClick={() => void onUpdate?.(booking, 'cancelled')} disabled={busy}>Joylarni bo‘shatish</button>}</>}</div></article>
}

function Empty({ icon, title, text }: { icon:ReactNode; title:string; text:string }) { return <div className="operator-empty">{icon}<b>{title}</b><p>{text}</p></div> }
