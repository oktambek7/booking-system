import { QRCodeSVG } from 'qrcode.react'
import { WifiOff, X } from 'lucide-react'
import Modal from './ui/Modal'
import { formatDateTime } from './dateFormat'
import type { OfflineTicket } from './offlineTickets'

type Lang = 'uz' | 'en' | 'ru'

const text: Record<Lang, Record<string, string>> = {
  uz: { offlineBare: 'Internet yo‘q. Aloqa tiklanguncha ba’zi imkoniyatlar ishlamaydi.', serverBare: 'Server hozir javob bermayapti. Qayta urinib ko‘ramiz.', serverTickets: 'Server hozir javob bermayapti. Saqlangan chiptalaringizni ko‘rishingiz mumkin.', retry: 'Qayta urinish', banner: 'Internet yo‘q. Saqlangan chiptalaringizni ko‘rishingiz mumkin.', open: 'Chiptalarni ko‘rsatish', title: 'Saqlangan chiptalar', note: 'Bu chiptalar telefoningizda saqlangan. Kirishda QR kodni ko‘rsating.', seats: 'O‘rindiqlar', code: 'Chipta kodi', close: 'Yopish' },
  en: { offlineBare: 'You are offline. Some features are unavailable until the connection returns.', serverBare: 'We can’t reach the server right now. We will keep trying.', serverTickets: 'We can’t reach the server right now. Your saved tickets are still available.', retry: 'Try again', banner: 'You are offline. Your saved tickets are still available.', open: 'Show tickets', title: 'Saved tickets', note: 'These tickets are saved on this device. Show the QR code at the entrance.', seats: 'Seats', code: 'Ticket code', close: 'Close' },
  ru: { offlineBare: 'Нет интернета. Часть функций недоступна, пока связь не вернётся.', serverBare: 'Сервер сейчас не отвечает. Мы продолжим попытки.', serverTickets: 'Сервер сейчас не отвечает. Сохранённые билеты доступны.', retry: 'Повторить', banner: 'Нет интернета. Сохранённые билеты доступны.', open: 'Показать билеты', title: 'Сохранённые билеты', note: 'Эти билеты сохранены на устройстве. Покажите QR-код на входе.', seats: 'Места', code: 'Код билета', close: 'Закрыть' },
}

/**
 * A slim bar above the page while a signed-out visitor either has no connection ("offline") or the API is not
 * answering although the device is online ("server"). Saved tickets can be opened in both cases.
 */
export function OfflineBanner({ lang, reason, hasTickets, onOpen, onRetry }:
  { lang: Lang; reason: 'offline' | 'server'; hasTickets: boolean; onOpen: () => void; onRetry: () => void }) {
  const t = text[lang]
  const message = reason === 'offline' ? (hasTickets ? t.banner : t.offlineBare) : (hasTickets ? t.serverTickets : t.serverBare)
  return (
    <div className="offline-banner" role="status">
      <WifiOff size={16} aria-hidden="true" />
      <span>{message}</span>
      {hasTickets && <button type="button" onClick={onOpen}>{t.open}</button>}
      {reason === 'server' && <button type="button" onClick={onRetry}>{t.retry}</button>}
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
            <QRCodeSVG value={ticket.ticket_code} size={132} level="M" includeMargin title={`QR ${ticket.ticket_code}`} />
          </li>
        ))}
      </ul>
    </Modal>
  )
}
