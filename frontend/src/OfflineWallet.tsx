import { QRCodeSVG } from 'qrcode.react'
import { WifiOff, X } from 'lucide-react'
import Modal from './ui/Modal'
import { formatDateTime } from './dateFormat'
import type { OfflineTicket } from './offlineTickets'

type Lang = 'uz' | 'en' | 'ru'

const text: Record<Lang, Record<string, string>> = {
  uz: { banner: 'Internet yo‘q. Saqlangan chiptalaringizni ko‘rishingiz mumkin.', open: 'Chiptalarni ko‘rsatish', title: 'Saqlangan chiptalar', note: 'Bu chiptalar telefoningizda saqlangan. Kirishda QR kodni ko‘rsating.', seats: 'O‘rindiqlar', code: 'Chipta kodi', close: 'Yopish' },
  en: { banner: 'You are offline. Your saved tickets are still available.', open: 'Show tickets', title: 'Saved tickets', note: 'These tickets are saved on this device. Show the QR code at the entrance.', seats: 'Seats', code: 'Ticket code', close: 'Close' },
  ru: { banner: 'Нет интернета. Сохранённые билеты доступны.', open: 'Показать билеты', title: 'Сохранённые билеты', note: 'Эти билеты сохранены на устройстве. Покажите QR-код на входе.', seats: 'Места', code: 'Код билета', close: 'Закрыть' },
}

/** A slim bar shown while the API cannot be reached and the device holds saved tickets. */
export function OfflineBanner({ lang, onOpen }: { lang: Lang; onOpen: () => void }) {
  return (
    <div className="offline-banner" role="status">
      <WifiOff size={16} aria-hidden="true" />
      <span>{text[lang].banner}</span>
      <button type="button" onClick={onOpen}>{text[lang].open}</button>
    </div>
  )
}

/** The saved tickets with their QR codes, drawn on the device, so they work with no connection at all. */
export default function OfflineTickets({ tickets, lang, onClose }: { tickets: OfflineTicket[]; lang: Lang; onClose: () => void }) {
  const t = (key: string) => text[lang][key]
  return (
    <Modal scrimClassName="ticket-scrim" className="offline-tickets" label={t('title')} onClose={onClose}>
      <header className="offline-tickets-head">
        <h2>{t('title')}</h2>
        <button type="button" className="icon-button" onClick={onClose} aria-label={t('close')}><X /></button>
      </header>
      <p className="offline-tickets-note">{t('note')}</p>
      <ul className="offline-ticket-list">
        {tickets.map(ticket => (
          <li key={ticket.id} className="offline-ticket">
            <div className="offline-ticket-info">
              <h3>{ticket.movie_title}</h3>
              <p>{ticket.cinema_name} · {ticket.auditorium_name}</p>
              <p>{formatDateTime(ticket.starts_at, lang)}</p>
              <p>{t('seats')}: <b>{ticket.seats.join(', ')}</b></p>
              <p>{t('code')}: <b>{ticket.ticket_code}</b></p>
            </div>
            <QRCodeSVG value={ticket.ticket_code} size={132} level="M" includeMargin />
          </li>
        ))}
      </ul>
    </Modal>
  )
}
