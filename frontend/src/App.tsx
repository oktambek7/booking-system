import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUpRight, Check, ChevronDown, Clock3, Flower2, Menu, ShieldCheck, Sparkles, X } from 'lucide-react'
import AdminDashboard from './AdminDashboard'

type Service = { id:number; name:string; description:string; duration_minutes:number; price:number|string; active?:boolean }
type Provider = { id:number; name:string; bio:string; active:boolean; service_ids:number[] }
type Slot = { starts_at:string; ends_at:string }
type Booking = { id:number; service_id:number; provider_id:number; starts_at:string; ends_at:string; status:string; price_at_booking:number|string }
type User = { id:number; name:string; email:string; role:string }

const API = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
const demoServices:Service[] = [
  {id:1,name:'Signature haircut',description:'A considered cut, finished just the way you like it.',duration_minutes:45,price:180000},
  {id:2,name:'Glow facial',description:'A gentle reset for skin that needs a little love.',duration_minutes:60,price:260000},
  {id:3,name:'Manicure ritual',description:'Shape, care and a color that feels like you.',duration_minutes:50,price:150000},
]
const demoProviders:Provider[] = [
  {id:1,name:'Malika R.',bio:'Hair artist · 6 years of making people feel like themselves.',active:true,service_ids:[1]},
  {id:2,name:'Nodira A.',bio:'Skincare specialist · gentle hands, thoughtful care.',active:true,service_ids:[2]},
  {id:3,name:'Aziza K.',bio:'Nail artist · tiny details, very good energy.',active:true,service_ids:[3]},
]
const photos=[
  'https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1570172619644-dfd03ed5d881?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1610992015732-2449b76344bc?auto=format&fit=crop&w=1000&q=85',
]
const money=(value:number|string)=>new Intl.NumberFormat('uz-UZ').format(Number(value))+' so‘m'
const dayKey=(d:Date)=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
const prettyTashkent=(value:string,opts:Intl.DateTimeFormatOptions)=>new Intl.DateTimeFormat('en-US',{...opts,timeZone:'Asia/Tashkent'}).format(new Date(value))

export default function App(){
  const [services,setServices]=useState<Service[]>(demoServices)
  const [providers,setProviders]=useState<Provider[]>(demoProviders)
  const [bookings,setBookings]=useState<Booking[]>([])
  const [service,setService]=useState<Service|null>(null)
  const [provider,setProvider]=useState<Provider|null>(null)
  const [selectedDay,setSelectedDay]=useState(dayKey(new Date(Date.now()+86400000)))
  const [slots,setSlots]=useState<Slot[]>([])
  const [chosen,setChosen]=useState<Slot|null>(null)
  const [user,setUser]=useState<User|null>(()=>{try{return JSON.parse(localStorage.getItem('sana_user')||'null')}catch{return null}})
  const [token,setToken]=useState(localStorage.getItem('sana_token')||'')
  const [authOpen,setAuthOpen]=useState(false)
  const [authMode,setAuthMode]=useState<'login'|'register'>('login')
  const [historyOpen,setHistoryOpen]=useState(false)
  const [adminOpen,setAdminOpen]=useState(false)
  const [loading,setLoading]=useState(false)
  const [notice,setNotice]=useState('')
  const [mobileOpen,setMobileOpen]=useState(false)
  const demo=!API
  const days=useMemo(()=>Array.from({length:7},(_,i)=>{const d=new Date();d.setHours(0,0,0,0);d.setDate(d.getDate()+i+1);return d}),[])

  useEffect(()=>{if(!API)return; fetch(`${API}/api/services`).then(r=>r.ok?r.json():Promise.reject()).then(setServices).catch(()=>setNotice('Could not reach the booking API. Please try again soon.'))},[])
  useEffect(()=>{if(!service)return; if(demo){setProviders(demoProviders.filter(p=>p.service_ids.includes(service.id)));return}
    fetch(`${API}/api/providers?service_id=${service.id}`).then(r=>r.ok?r.json():Promise.reject()).then(setProviders).catch(()=>setProviders([]))
  },[service,demo])
  useEffect(()=>{if(!service||!provider)return;setChosen(null);if(demo){
    const date=new Date(`${selectedDay}T00:00:00`);const now=new Date();const dayStart=new Date(date);dayStart.setHours(9,0,0,0);const dayEnd=new Date(date);dayEnd.setHours(17,0,0,0);const list:Slot[]=[]
    for(let at=dayStart;at.getTime()+service.duration_minutes*60000<=dayEnd.getTime();at=new Date(at.getTime()+15*60000)){if(at>now)list.push({starts_at:at.toISOString(),ends_at:new Date(at.getTime()+service.duration_minutes*60000).toISOString()})}
    setSlots(list.filter(s=>!bookings.some(b=>b.provider_id===provider.id&&b.status!=='cancelled'&&new Date(b.starts_at)<new Date(s.ends_at)&&new Date(b.ends_at)>new Date(s.starts_at))))
    return
  }
    fetch(`${API}/api/availability?service_id=${service.id}&provider_id=${provider.id}&date=${selectedDay}`).then(r=>r.ok?r.json():Promise.reject()).then(setSlots).catch(()=>setSlots([]))
  },[service,provider,selectedDay,demo,bookings])
  useEffect(()=>{if(!token)return;if(demo){setBookings(JSON.parse(localStorage.getItem('sana_bookings')||'[]'));return}
    fetch(`${API}/api/bookings`,{headers:{Authorization:`Bearer ${token}`}}).then(r=>r.ok?r.json():Promise.reject()).then(setBookings).catch(()=>{})
  },[token,demo])
  const providersForService=providers.filter(p=>p.active&&p.service_ids.includes(service?.id||-1))
  const chooseService=(item:Service)=>{setService(item);setProvider(null);setChosen(null);setNotice('');document.getElementById('booking')?.scrollIntoView({behavior:'smooth',block:'start'})}
  const signOut=()=>{localStorage.removeItem('sana_token');localStorage.removeItem('sana_user');setToken('');setUser(null);setBookings([])}
  async function authSubmit(e:FormEvent<HTMLFormElement>){e.preventDefault();const form=new FormData(e.currentTarget);setLoading(true)
    try{if(demo){const email=String(form.get('email'));const name=String(form.get('name')||email.split('@')[0]);const who={id:1,name,email,role:'customer'};localStorage.setItem('sana_token','demo');localStorage.setItem('sana_user',JSON.stringify(who));setToken('demo');setUser(who)}else{
      const route=authMode==='register'?'/api/auth/register':'/api/auth/login';const payload=authMode==='register'?{name:form.get('name'),email:form.get('email'),password:form.get('password')}:{email:form.get('email'),password:form.get('password')};const r=await fetch(`${API}${route}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!r.ok)throw new Error((await r.json()).detail||'Could not sign in');let who:User
      if(authMode==='register'){const lr=await fetch(`${API}/api/auth/login`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:form.get('email'),password:form.get('password')})});if(!lr.ok)throw new Error('Account created. Please sign in.');const auth=await lr.json();const me=await fetch(`${API}/api/auth/me`,{headers:{Authorization:`Bearer ${auth.access_token}`}});who=await me.json();localStorage.setItem('sana_token',auth.access_token)}else{const auth=r.status===200?await r.json():null;who={id:0,name:'',email:String(form.get('email')),role:'customer'};if(auth?.access_token){localStorage.setItem('sana_token',auth.access_token);const me=await fetch(`${API}/api/auth/me`,{headers:{Authorization:`Bearer ${auth.access_token}`}});who=await me.json()}}setToken(localStorage.getItem('sana_token')||'');setUser(who);localStorage.setItem('sana_user',JSON.stringify(who))}
      setAuthOpen(false);setNotice('You’re signed in. Your appointment is one little step away.')
    }catch(err){setNotice(err instanceof Error?err.message:'Something went wrong')}finally{setLoading(false)}
  }
  async function book(){if(!service||!provider||!chosen)return;if(!user){setAuthMode('login');setAuthOpen(true);return}setLoading(true)
    try{let item:Booking;if(demo){item={id:Date.now(),service_id:service.id,provider_id:provider.id,starts_at:chosen.starts_at,ends_at:chosen.ends_at,status:'confirmed',price_at_booking:service.price};const next=[item,...bookings];setBookings(next);localStorage.setItem('sana_bookings',JSON.stringify(next))}else{const r=await fetch(`${API}/api/bookings`,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify({service_id:service.id,provider_id:provider.id,starts_at:chosen.starts_at})});if(!r.ok){const detail=(await r.json()).detail;throw new Error(r.status===409?'That time was just taken. Choose another slot.':detail||'Could not create booking')}item=await r.json();setBookings([item,...bookings])}
      setNotice(`You’re booked for ${prettyTashkent(item.starts_at,{weekday:'long',month:'long',day:'numeric'})} at ${prettyTashkent(item.starts_at,{hour:'numeric',minute:'2-digit'})}.`);setChosen(null)
    }catch(err){setNotice(err instanceof Error?err.message:'Could not book this time')}finally{setLoading(false)}
  }
  async function cancelBooking(item:Booking){try{if(!demo){const r=await fetch(`${API}/api/bookings/${item.id}/status`,{method:'PATCH',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify({status:'cancelled'})});if(!r.ok)throw new Error('Could not cancel this booking')};const next=bookings.map(b=>b.id===item.id?{...b,status:'cancelled'}:b);setBookings(next);if(demo)localStorage.setItem('sana_bookings',JSON.stringify(next))}catch(err){setNotice(err instanceof Error?err.message:'Could not cancel') }}

  return <>
    <header className="topbar"><a className="brand" href="#top"><span className="brand-icon"><Flower2 size={21}/></span>sana<span className="brand-dot">.</span></a>
      <nav className={mobileOpen?'nav nav-open':'nav'}><a href="#services" onClick={()=>setMobileOpen(false)}>Services</a><a href="#story" onClick={()=>setMobileOpen(false)}>Our space</a><button className="nav-book" onClick={()=>document.getElementById('services')?.scrollIntoView({behavior:'smooth'})}>Book a visit <ArrowUpRight size={15}/></button></nav>
      <div className="top-actions">{user?.role==='admin'&&<button className="admin-shortcut" onClick={()=>setAdminOpen(true)}>Studio <span>ADMIN</span><ArrowUpRight size={13}/></button>}{user?<button className="user-pill" onClick={()=>setHistoryOpen(true)}><span className="avatar">{user.name.slice(0,1).toUpperCase()}</span><span className="user-name">{user.name}</span><ChevronDown size={14}/></button>:<button className="login-link" onClick={()=>{setAuthMode('login');setAuthOpen(true)}}>Sign in <ArrowUpRight size={15}/></button>}<button className="mobile-menu" aria-label="Toggle navigation" onClick={()=>setMobileOpen(!mobileOpen)}>{mobileOpen?<X/>:<Menu/>}</button></div>
    </header>
    <main id="top">
      <section className="hero"><div className="hero-copy"><div className="eyebrow"><span className="eyebrow-line"/> YOUR LITTLE PAUSE IN THE CITY</div><h1>A little time<br/>for <em>yourself.</em></h1><p className="hero-desc">Good people, thoughtful care, and a moment that’s just yours. Find your feel good, right here in Tashkent.</p><a href="#services" className="primary-btn">Find your moment <ArrowDown size={16}/></a><div className="hero-proof"><div className="proof-avatars"><span>M</span><span>N</span><span>A</span><b>+</b></div><p><strong>4.9/5</strong><br/>from 1,200+ happy visits</p></div><span className="hero-side-note">GOOD DAYS START HERE <span>↘</span></span></div>
        <div className="hero-art"><img className="hero-photo" src="https://images.unsplash.com/photo-1600334129128-685c5582fd35?auto=format&fit=crop&w=1400&q=90" alt="Sunlit, calm beauty studio interior"/><div className="hero-image-wash"/><div className="hero-stamp"><span>MAKE SPACE</span><Flower2 size={25}/><span>FOR YOU</span></div><div className="hero-note"><span className="note-spark">✳</span><span>slow down.<br/>you’re right on time.</span></div><div className="image-index">01 <span/> 03</div></div>
      </section>
      <section className="trust-strip"><div><Sparkles size={16}/> <span>Thoughtful people</span></div><i/><div><ShieldCheck size={16}/> <span>Easy, secure booking</span></div><i/><div><Flower2 size={16}/> <span>A little more you</span></div><span className="strip-location">TASHKENT, UZBEKISTAN&nbsp; · &nbsp;41°18′N 69°16′E</span></section>
      <section id="services" className="services-section"><div className="section-heading"><div><div className="eyebrow"><span className="eyebrow-line"/> THE GOOD STUFF</div><h2>What would feel <em>good?</em></h2></div><p>Small rituals, made with care.<br/>Pick one and we’ll take it from here.</p></div>
        <div className="service-grid">{services.map((s,i)=><button key={s.id} className={`service-card ${service?.id===s.id?'service-selected':''}`} onClick={()=>chooseService(s)}><div className="service-image-wrap"><img src={photos[i%photos.length]} alt={s.name}/><span className="service-number">0{i+1}</span><span className="service-arrow"><ArrowUpRight size={18}/></span></div><div className="service-meta"><div><h3>{s.name}</h3><p>{s.description}</p></div><span className="service-price">{money(s.price)}</span></div><div className="service-duration"><Clock3 size={13}/>{s.duration_minutes} min <span>·</span><span>Made for you</span></div></button>)}</div>
      </section>
      <section id="booking" className="booking-section"><div className="booking-heading"><div><div className="eyebrow"><span className="eyebrow-line"/> THE NEXT LITTLE STEP</div><h2>Make it <em>yours.</em></h2></div><div className="booking-steps"><span className={!service?'step-active':''}>01 <i/> service</span><span className={!provider?'step-active':''}>02 <i/> your person</span><span className={!chosen?'step-active':''}>03 <i/> your time</span></div></div>
        {!service?<div className="booking-empty"><div className="empty-flower"><Flower2 size={25}/></div><p>First, choose something that feels good.</p><a href="#services">Explore our services <ArrowRight size={15}/></a></div>:<div className="booking-panel">
          <div className="booking-left"><div className="booking-label"><span className="step-num">01</span><div><span className="mini-label">YOUR TREATMENT</span><h3>{service.name}</h3></div><button className="change-btn" onClick={()=>{setService(null);setProvider(null)}}>Change</button></div><div className="provider-picker"><div className="picker-label"><span className="step-num">02</span><div><span className="mini-label">THE PERSON</span><h3>Who would you like to see?</h3></div></div><div className="provider-list">{providersForService.map((p,i)=><button key={p.id} className={`provider-option ${provider?.id===p.id?'provider-active':''}`} onClick={()=>setProvider(p)}><span className={`provider-avatar tone-${i%3}`}>{p.name.split(' ').map(x=>x[0]).slice(0,2).join('')}</span><span className="provider-copy"><b>{p.name}</b><small>{p.bio.split('·')[0]}</small></span><span className="radio-dot">{provider?.id===p.id&&<Check size={12}/>}</span></button>)}{providersForService.length===0&&<p className="quiet">No team members available right now.</p>}</div></div></div>
          <div className="booking-right"><div className="picker-label"><span className="step-num">03</span><div><span className="mini-label">THE MOMENT</span><h3>Pick a day & time</h3></div></div><div className="date-row"><button className="date-nav" aria-label="Previous week" onClick={()=>{const d=new Date(`${selectedDay}T00:00:00`);d.setDate(d.getDate()-7);if(d>=new Date(new Date().setHours(0,0,0,0)))setSelectedDay(dayKey(d))}}><ArrowLeft size={15}/></button>{days.map(day=><button key={dayKey(day)} className={`day-chip ${selectedDay===dayKey(day)?'day-active':''}`} onClick={()=>setSelectedDay(dayKey(day))}><small>{new Intl.DateTimeFormat('en-US',{weekday:'short'}).format(day)}</small><b>{day.getDate()}</b></button>)}<button className="date-nav" aria-label="Next week" onClick={()=>{const d=new Date(`${selectedDay}T00:00:00`);d.setDate(d.getDate()+7);setSelectedDay(dayKey(d))}}><ArrowRight size={15}/></button></div><div className="time-grid">{!provider?<p className="quiet time-empty">Choose your person to see their times.</p>:slots.length?slots.map(slot=><button key={slot.starts_at} className={`time-chip ${chosen?.starts_at===slot.starts_at?'time-active':''}`} onClick={()=>setChosen(slot)}>{prettyTashkent(slot.starts_at,{hour:'numeric',minute:'2-digit'})}</button>):<p className="quiet time-empty">No times left that day. Try another date.</p>}</div><div className="booking-footer"><div className="booking-total"><span>YOUR TOTAL</span><b>{money(service.price)}</b><small>{service.duration_minutes} minutes · no surprises</small></div><button disabled={!chosen||loading} className="confirm-btn" onClick={book}>{loading?'One sec…':user?'Confirm visit':'Continue'} <ArrowRight size={16}/></button></div></div>
        </div>}
        {notice&&<div className="notice"><span><Check size={16}/></span>{notice}<button onClick={()=>setNotice('')} aria-label="Dismiss"><X size={15}/></button></div>}
      </section>
      <section id="story" className="story-section"><div className="story-image"><img src="https://images.unsplash.com/photo-1600948836101-f9ffda59d250?auto=format&fit=crop&w=1100&q=85" alt="Warm natural light in the Sana studio"/><span className="story-image-label">A SOFTER KIND OF SELF-CARE</span></div><div className="story-copy"><div className="eyebrow"><span className="eyebrow-line"/> A NOTE FROM US</div><h2>Come as you are.<br/><em>Leave a little lighter.</em></h2><p>We made Sana for the days you need a reset, a refresh, or just an hour that belongs to you. No rush, no fuss. Just good care from people who care.</p><div className="story-sign"><span className="sign-mark">s.</span><span>With care, always<br/><b>The Sana team</b></span></div><a className="text-link" href="#services">Find your feel good <ArrowUpRight size={15}/></a></div><div className="story-side">A LITTLE PAUSE, A LOT OF GOOD.</div></section>
      <section className="closing-cta"><span className="closing-flower"><Flower2 size={28}/></span><h2>Your next good day<br/>is <em>right here.</em></h2><a href="#services" className="primary-btn">Let’s make a little time <ArrowUpRight size={16}/></a><span className="closing-script">see you soon ♡</span></section>
    </main>
    <footer className="footer"><a className="brand" href="#top"><span className="brand-icon"><Flower2 size={20}/></span>sana<span className="brand-dot">.</span></a><span>GOOD CARE. GOOD PEOPLE. GOOD DAYS.</span><span>© 2026 SANA STUDIO · TASHKENT</span></footer>
    {demo&&<div className="demo-badge"><span/> Interactive demo</div>}
    {authOpen&&<div className="overlay" onMouseDown={e=>{if(e.target===e.currentTarget)setAuthOpen(false)}}><div className="auth-card"><button className="modal-close" onClick={()=>setAuthOpen(false)}><X size={18}/></button><div className="auth-flower"><Flower2 size={24}/></div><div className="eyebrow centered"><span className="eyebrow-line"/> YOUR LITTLE PAUSE</div><h2>{authMode==='login'?'Good to see you.':'Let’s make it official.'}</h2><p>{authMode==='login'?'Sign in to make your booking yours.':'A few details and your moment is saved.'}</p><form onSubmit={authSubmit}>{authMode==='register'&&<label>Your name<input name="name" autoComplete="name" required placeholder="What should we call you?"/></label>}<label>Email address<input type="email" name="email" autoComplete="email" required placeholder="you@example.com"/></label><label>Password<input type="password" name="password" autoComplete={authMode==='login'?'current-password':'new-password'} minLength={10} required placeholder="At least 10 characters"/></label><button className="confirm-btn auth-submit" disabled={loading}>{loading?'One sec…':authMode==='login'?'Sign in':'Create account'} <ArrowRight size={16}/></button></form>{notice&&<p className="auth-error">{notice}</p>}<div className="auth-switch">{authMode==='login'?"New to Sana?":"Already have an account?"} <button onClick={()=>{setNotice('');setAuthMode(authMode==='login'?'register':'login')}}>{authMode==='login'?'Create an account':'Sign in'}</button></div><span className="auth-privacy"><ShieldCheck size={13}/> Your details stay private with us.</span></div></div>}
    {historyOpen&&<div className="overlay" onMouseDown={e=>{if(e.target===e.currentTarget)setHistoryOpen(false)}}><aside className="history-panel"><div className="history-head"><div><div className="eyebrow"><span className="eyebrow-line"/> YOUR LITTLE PLANS</div><h2>Your visits<span className="brand-dot">.</span></h2></div><button className="modal-close" onClick={()=>setHistoryOpen(false)}><X size={18}/></button></div><p className="history-greeting">A little time for {user?.name}.</p>{bookings.length===0?<div className="history-empty"><Flower2 size={27}/><b>Nothing on the calendar yet.</b><span>There’s always time for a little you.</span><button onClick={()=>{setHistoryOpen(false);document.getElementById('services')?.scrollIntoView({behavior:'smooth'})}}>Find a service <ArrowRight size={15}/></button></div>:<div className="history-list">{bookings.map(b=>{const s=services.find(x=>x.id===b.service_id);const p=[...providers,...demoProviders].find(x=>x.id===b.provider_id);return <article className="history-card" key={b.id}><div className="history-card-top"><span className={`status-dot status-${b.status}`}/><span>{b.status}</span><span className="history-ref">#{String(b.id).slice(-5)}</span></div><h3>{s?.name||'Your appointment'}</h3><p>{p?.name||'Sana team'}</p><div className="history-date"><Clock3 size={14}/>{prettyTashkent(b.starts_at,{weekday:'long',month:'long',day:'numeric'})} · {prettyTashkent(b.starts_at,{hour:'numeric',minute:'2-digit'})}</div>{b.status!=='cancelled'&&b.status!=='completed'&&<button className="cancel-btn" onClick={()=>cancelBooking(b)}>Cancel booking</button>}</article>})}</div>}<button className="signout-btn" onClick={()=>{signOut();setHistoryOpen(false)}}>Sign out <ArrowRight size={14}/></button></aside></div>}
    {adminOpen&&user?.role==='admin'&&<AdminDashboard api={API} token={token} onClose={()=>setAdminOpen(false)}/>}
  </>
}
