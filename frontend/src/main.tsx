import React from 'react'
import ReactDOM from 'react-dom/client'
import '@fontsource-variable/unbounded'
import '@fontsource-variable/manrope'
import App from './App'
import './styles/index.css'

// Offline support: only in production builds, after the page has loaded so it never competes with first paint.
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => { void navigator.serviceWorker.register('/sw.js').catch(() => undefined) })
}

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
