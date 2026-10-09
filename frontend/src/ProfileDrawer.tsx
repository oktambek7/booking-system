import { Camera, LogOut, Save, X } from 'lucide-react'
import { useState, type ChangeEvent, type FormEvent } from 'react'

type Lang = 'uz' | 'en' | 'ru'
export type ProfileUser = {id:number;nickname:string;email:string;role:string;created_at?:string;avatar_data?:string|null}

const text:Record<Lang,Record<string,string>> = {
  uz:{profile:'Profil',account:'Hisob',username:'Foydalanuvchi nomi',email:'Email',memberSince:'Parda foydalanuvchisi bo‘lgan sana',picture:'Profil rasmi',changePicture:'Rasm tanlash',save:'O‘zgarishlarni saqlash',saving:'Saqlanmoqda…',signOut:'Tizimdan chiqish',close:'Yopish',imageError:'PNG, JPEG yoki WebP rasmini tanlang. Rasm 8 MB dan kichik bo‘lishi kerak.',profileError:'Profilni saqlab bo‘lmadi.'},
  en:{profile:'Profile',account:'Account',username:'Username',email:'Email',memberSince:'Parda member since',picture:'Profile photo',changePicture:'Choose photo',save:'Save changes',saving:'Saving…',signOut:'Sign out',close:'Close',imageError:'Choose a PNG, JPEG, or WebP image smaller than 8 MB.',profileError:'Could not save your profile.'},
  ru:{profile:'Профиль',account:'Аккаунт',username:'Имя пользователя',email:'Email',memberSince:'Пользователь Parda с',picture:'Фото профиля',changePicture:'Выбрать фото',save:'Сохранить изменения',saving:'Сохранение…',signOut:'Выйти',close:'Закрыть',imageError:'Выберите PNG, JPEG или WebP размером до 8 МБ.',profileError:'Не удалось сохранить профиль.'}
}

function resizeAvatar(file:File):Promise<string>{
  if(!file.type.match(/^image\/(png|jpeg|webp)$/)||file.size>8*1024*1024)throw new Error('image')
  return new Promise((resolve,reject)=>{
    const source=URL.createObjectURL(file),image=new Image()
    image.onload=()=>{
      const scale=Math.min(1,320/Math.max(image.naturalWidth,image.naturalHeight))
      const canvas=document.createElement('canvas')
      canvas.width=Math.max(1,Math.round(image.naturalWidth*scale))
      canvas.height=Math.max(1,Math.round(image.naturalHeight*scale))
      canvas.getContext('2d')?.drawImage(image,0,0,canvas.width,canvas.height)
      URL.revokeObjectURL(source)
      resolve(canvas.toDataURL('image/webp',.82))
    }
    image.onerror=()=>{URL.revokeObjectURL(source);reject(new Error('image'))}
    image.src=source
  })
}

export default function ProfileDrawer({user,lang,onClose,onSave,onSignOut}:{user:ProfileUser;lang:Lang;onClose:()=>void;onSave:(nickname:string,avatarData:string|null)=>Promise<void>;onSignOut:()=>void}){
  const t=(key:keyof typeof text.en)=>text[lang][key]
  const [nickname,setNickname]=useState(user.nickname),[avatar,setAvatar]=useState(user.avatar_data||null),[busy,setBusy]=useState(false),[error,setError]=useState('')
  const initial=(user.nickname.trim().charAt(0)||'P').toUpperCase()
  const joined=user.created_at?new Intl.DateTimeFormat(lang==='uz'?'uz-UZ':lang==='ru'?'ru-RU':'en-US',{dateStyle:'medium'}).format(new Date(user.created_at)):''
  const chooseAvatar=async(event:ChangeEvent<HTMLInputElement>)=>{
    const file=event.target.files?.[0]
    if(!file)return
    try{setError('');setAvatar(await resizeAvatar(file))}catch{setError(t('imageError'))}
  }
  const submit=async(event:FormEvent)=>{
    event.preventDefault();setBusy(true);setError('')
    try{await onSave(nickname,avatar)}catch(reason){setError(reason instanceof Error?reason.message:t('profileError'))}finally{setBusy(false)}
  }
  return <div className="modal-scrim profile-scrim" onMouseDown={event=>event.target===event.currentTarget&&onClose()}><aside className="profile-drawer" role="dialog" aria-modal="true" aria-label={t('profile')}><header><div><span>{t('account')}</span><h2>{t('profile')}</h2></div><button className="icon-button" onClick={onClose} aria-label={t('close')}><X/></button></header><form onSubmit={submit}><section className="profile-identity"><label className="profile-avatar-editor"><input className="profile-avatar-input" type="file" accept="image/png,image/jpeg,image/webp" onChange={event=>void chooseAvatar(event)}/>{avatar?<img src={avatar} alt=""/>:<b>{initial}</b>}<span><Camera size={16}/>{t('changePicture')}</span></label><div><h3>{nickname||user.nickname}</h3><p>{user.email}</p>{joined&&<small>{t('memberSince')} · {joined}</small>}</div></section><div className="profile-fields"><label>{t('username')}<input value={nickname} minLength={2} maxLength={40} pattern="[A-Za-z0-9_.-]+" onChange={event=>setNickname(event.target.value)} required/></label></div>{error&&<p className="dialog-error">{error}</p>}<button className="button-primary profile-save" disabled={busy}>{busy?t('saving'):<><Save size={16}/>{t('save')}</>}</button></form><button className="profile-signout" onClick={onSignOut}><LogOut size={16}/>{t('signOut')}</button></aside></div>
}
