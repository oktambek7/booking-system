import { Check, Clock, X } from 'lucide-react'
import Modal from './ui/Modal'
import type { PaymentOutcome } from './paymentReturn'

type Lang = 'uz' | 'en' | 'ru'
type Strings = Record<PaymentOutcome | `${PaymentOutcome}Title` | 'ok', string>

const text: Record<Lang, Strings> = {
  uz: {
    paid: 'To‘lov qabul qilindi. Chiptangiz “Mening buyurtmalarim” bo‘limida.', paidTitle: 'To‘lov muvaffaqiyatli',
    refunded: 'To‘lov o‘rindiqlar bo‘shatilganidan keyin keldi, shuning uchun pul qaytarildi. Joylarni qayta tanlang.', refundedTitle: 'Pul qaytarildi',
    failed: 'To‘lov amalga oshmadi. Hech narsa yechilmadi, qayta urinib ko‘ring.', failedTitle: 'To‘lov bekor qilindi',
    pending: 'To‘lov hali tasdiqlanmadi. Bir necha daqiqadan keyin “Mening buyurtmalarim”ni tekshiring.', pendingTitle: 'Tasdiqlanmoqda', ok: 'Yaxshi',
  },
  en: {
    paid: 'Payment received. Your ticket is in My bookings.', paidTitle: 'Payment successful',
    refunded: 'The payment arrived after the seats were released, so it was returned to you. Please choose seats again.', refundedTitle: 'Payment returned',
    failed: 'The payment did not go through. Nothing was charged; please try again.', failedTitle: 'Payment cancelled',
    pending: 'The payment is not confirmed yet. Check My bookings in a few minutes.', pendingTitle: 'Confirming', ok: 'OK',
  },
  ru: {
    paid: 'Оплата получена. Билет в разделе «Мои заказы».', paidTitle: 'Оплата прошла',
    refunded: 'Оплата пришла после освобождения мест, поэтому деньги возвращены. Выберите места снова.', refundedTitle: 'Деньги возвращены',
    failed: 'Оплата не прошла. Деньги не списаны, попробуйте снова.', failedTitle: 'Оплата отменена',
    pending: 'Оплата ещё не подтверждена. Проверьте «Мои заказы» через несколько минут.', pendingTitle: 'Подтверждение', ok: 'Хорошо',
  },
}

/** The answer shown after the customer returns from a provider's hosted payment page. */
export default function PaymentResult({ outcome, lang, onClose }: { outcome: PaymentOutcome; lang: Lang; onClose: () => void }) {
  const Icon = outcome === 'paid' ? Check : outcome === 'pending' ? Clock : X
  const strings = text[lang]
  return (
    <Modal className="confirm-dialog" label={strings[`${outcome}Title`]} onClose={onClose}>
      <div className="confirm-icon"><Icon /></div>
      <h2>{strings[`${outcome}Title`]}</h2>
      <p>{strings[outcome]}</p>
      <button className="button-primary" onClick={onClose}>{strings.ok}</button>
    </Modal>
  )
}
