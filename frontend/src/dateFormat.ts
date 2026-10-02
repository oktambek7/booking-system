export type DisplayLanguage = 'uz' | 'en' | 'ru'

const months: Record<DisplayLanguage, string[]> = {
  uz: ['Yan', 'Fev', 'Mar', 'Apr', 'May', 'Iyun', 'Iyul', 'Avg', 'Sen', 'Okt', 'Noy', 'Dek'],
  en: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
  ru: ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'],
}

const weekdays: Record<DisplayLanguage, string[]> = {
  uz: ['Yak', 'Du', 'Se', 'Chor', 'Pay', 'Jum', 'Shan'],
  en: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
  ru: ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'],
}

const englishWeekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function partsFor(value: string | Date) {
  const values = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Tashkent', weekday: 'short', year: 'numeric', month: 'numeric', day: 'numeric',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(value))
  return Object.fromEntries(values.filter(part => part.type !== 'literal').map(part => [part.type, part.value]))
}

export function calendarDate(iso: string, lang: DisplayLanguage) {
  const match = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (!match) return iso
  const month = Number(match[2])
  const day = Number(match[3])
  return month >= 1 && month <= 12 && day >= 1 && day <= 31 ? `${months[lang][month - 1]} ${day}` : iso
}

export function weekdayForDate(iso: string, lang: DisplayLanguage) {
  const match = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (!match) return ''
  const weekday = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))).getUTCDay()
  return weekdays[lang][weekday]
}

export function formatDateTime(value: string, lang: DisplayLanguage) {
  const parts = partsFor(value)
  const weekday = weekdays[lang][englishWeekdays.indexOf(parts.weekday)] || parts.weekday
  const month = months[lang][Number(parts.month) - 1] || parts.month
  return `${weekday} · ${month} ${Number(parts.day)}, ${parts.hour}:${parts.minute}`
}

export function isoDateInTashkent(value: Date) {
  const parts = partsFor(value)
  return `${parts.year}-${parts.month.padStart(2, '0')}-${parts.day.padStart(2, '0')}`
}
