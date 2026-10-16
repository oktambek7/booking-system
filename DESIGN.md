---
name: Phantora
description: An Uzbek-first cinema booking experience set in a darkened auditorium: ink surfaces, ivory type, one gold accent. Dark by default, with a matching ivory theme.
colors:
  ink: "#0B0D17"
  ink-deep: "#07080F"
  ink-raised: "#2A2E45"
  ivory: "#F1ECE2"
  gold: "#C9A25B"
  gold-deep: "#A8823D"
  dusk: "#8A8FA6"
  bg: "#0B0D17"
  bg-elevated: "#10131F"
  bg-solid-3: "#1C2036"
  text: "#F1ECE2"
  text-2: "#BDBAB4"
  text-3: "#9A9EB2"
  accent-text: "#C9A25B"
  focus-ring: "#E0BE7F"
  action-from: "#D3AD68"
  action-to: "#BC9348"
  action-ink: "#0B0D17"
  seat-available: "#8A8FA6"
  seat-selected: "#C9A25B"
  seat-premium: "#F1ECE2"
  seat-taken: "#2A2E45"
  success-text: "#7FD3A8"
  warning-text: "#E6C27A"
  danger-text: "#FF9A94"
  light-bg: "#F1ECE2"
  light-text: "#0B0D17"
  light-text-2: "#3F4258"
  light-accent: "#A8823D"
  light-accent-text: "#7A5A1C"
typography:
  display:
    fontFamily: "Syne Variable, Manrope Variable, system-ui, sans-serif"
    fontSize: "clamp(1.75rem, 1.1rem + 3vw, 3.5rem)"
    fontWeight: 700
    lineHeight: 1.12
  body:
    fontFamily: "Outfit Variable, Manrope Variable, system-ui, sans-serif"
    fontSize: "1rem (16px)"
    fontWeight: 400
    lineHeight: 1.6
  numerals:
    fontFamily: "Outfit Variable, Manrope Variable, system-ui, sans-serif"
    note: "Prices, times, codes and counts. Syne draws its zero as a round o, so it is never used for digits."
  label:
    fontFamily: "Outfit Variable, Manrope Variable, system-ui, sans-serif"
    fontSize: "0.75rem (12px, the floor)"
    fontWeight: 700
rounded:
  sm: "8px"
  md: "14px"
  lg: "20px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "linear-gradient(135deg, {colors.action-from}, {colors.action-to})"
    textColor: "{colors.action-ink}"
    rounded: "{rounded.pill}"
    height: "48px"
  chip:
    backgroundColor: "surface-1"
    rounded: "{rounded.pill}"
    height: "40px"
  seat:
    size: "28-40px, scales with the hall width"
    rounded: "9px 9px 5px 5px"
---

# Design System: Phantora

## Overview

**Creative North Star: The Darkened Auditorium**

The brand mark is a ticket, so the interface behaves like one: a dark house, a single warm pool of light above the screen, and one gold detail that tells you where to go next. Ink does the work of the room, ivory is the projected type, dusk is everything quiet, and gold appears only where a decision is. It is the same restraint as the logo, where one gold dot sits among four ink ones.

Dark ("Ink") is the default because people book in the evening and a lit-down room suits a cinema. The light theme ("Ivory") is the same system on warm paper with ink type and a deeper gold; every component reads the same tokens in both.

The interface is Uzbek-first with Russian and English, prices in UZS, times in `Asia/Tashkent`. Film and showtime data comes from Cinematica and TMDB; checkout is a demo that never charges money.

**Key characteristics**
- One accent. Gold is the only chromatic colour; nothing else competes with it.
- Three surface levels over a still theatre backdrop (no animation behind content).
- One gold primary action per screen, always in the same place.
- Seat state told three ways: colour, pattern or icon, and text.
- Four breakpoints, 8px spacing grid, nothing under 12px.

## Brand

The assets come from the Phantora brand kit and are used unchanged.

- **Mark**: the ticket, drawn inline (`frontend/src/ui/Brand.tsx`) so the ticket takes the text colour (ivory on ink, ink on ivory) and the single dot always takes the accent. Minimum 24px.
- **Wordmark**: the kit's outlined Syne Bold lettering, filled with the text colour.
- **UI lockup**: mark plus wordmark. The print lockup sets the wordmark small beside a large ticket, which is unreadable at header size, so the interface lockup enlarges the wordmark relative to the mark (32px mark, 15px-high wordmark in the header; 28px and 14px in the footer). The artwork itself is untouched.
- **Icons and previews**: favicon (SVG, ICO, 16/32), apple-touch-icon, 192/512 PWA icons and the 1200x630 link preview are the kit's files. The maskable icon is the kit's app icon scaled to 80% on ink so it sits inside the safe zone.
- **Do not**: recolour the mark, add effects, put gold anywhere on the mark other than the dot, or use the wordmark in a face other than the supplied outlines.

## Colors

### Palette (identical in both themes)
- **Ink** `#0B0D17`: rooms, backgrounds, text on light. **Ink deep** `#07080F`: the far end of the backdrop. **Ink raised** `#2A2E45`: taken seats and hatching.
- **Ivory** `#F1ECE2`: type on dark, background on light.
- **Gold** `#C9A25B`: the accent. `#A8823D` on light backgrounds.
- **Dusk** `#8A8FA6`: secondary text, borders, available seats.

### Ink (dark, default)
- **Base** `#0B0D17`, **elevated** `#10131F`, surfaces `#121524`, `#171A2C`, `#1C2036`.
- **Text** `#F1ECE2` (16.5:1), **secondary** `#BDBAB4` (10.0:1), **tertiary** `#9A9EB2` (7.3:1, metadata only).
- **Primary action**: a gold gradient `#D3AD68` to `#BC9348` with ink text (8.1:1 at the light end, 6.8:1 at the dark end).
- **Focus ring** `#E0BE7F`.

### Ivory (light)
- **Base** `#F1ECE2`, surfaces `#FAF7F1`, `#ECE6D9`. **Text** `#0B0D17` (16.5:1), **secondary** `#3F4258` (8.4:1), **tertiary** `#5E6178` (5.2:1).
- **Gold as a fill or line** `#A8823D`; **gold as type** `#7A5A1C` (5.4:1), because `#A8823D` on ivory is only 3.1:1.
- The action gradient is the same gold with ink text, so the button is identical in both themes.

### Semantic (solid, never surface)
- Success `#4FB58A` / text `#7FD3A8` (dark), `#1E7A4E` / `#17603A` (light). Warning `#D9A441` / `#E6C27A`, `#8F6212` / `#7A5200`. Danger `#E5645F` / `#FF9A94`, `#B3261E`. Status text is always the `-text` token, never the fill.

### Seats
| State | Dark | Light | Also shown by |
|---|---|---|---|
| Available | dusk `#8A8FA6`, ink number | sand `#DCD7CA` with a dusk edge | the seat number |
| Selected | gold `#C9A25B`, ivory ring, glow | `#A8823D`, ink ring | a check mark |
| Premium | ivory `#F1ECE2` | ink `#0B0D17` | a gold corner dot |
| Taken | `#2A2E45` | `#C4BFB1` | a diagonal hatch, `aria-disabled` |

Gold and dusk are close in luminance, so a selected seat is never told apart by colour alone: it is the only seat with a check, a ring and a glow.

## Typography

**Display:** Syne (700), self-hosted through Fontsource, for headings, film titles and the brand. **Body and UI:** Outfit (400-700), self-hosted. **Numerals:** Outfit, through `--font-num`, for prices, showtimes, ticket codes, counts and the code input.

Neither face has Cyrillic, so Manrope is loaded as the fallback and Russian text falls through to it per glyph. Latin subsets (including the Uzbek `oʻ`/`gʻ` modifier letters) use `font-display: swap`. The CSP only allows `font-src 'self'`, so nothing loads from a font CDN.

- Hero `clamp(1.75rem, 1.1rem + 3vw, 3.5rem)`, H2 28-44px, H3 20-24px, body 16px, small 14px, label 12px (uppercase, +0.1em).
- Tabular numerals for times, prices and seat numbers. No kicker or eyebrow above headings.

## Surfaces

| Level | Used for | Dark fill | Light fill | Blur |
|---|---|---|---|---|
| `glass-1` | cards, chips, filter panel | ivory 4% | white 50% | 14px (10px on phones) |
| `glass-2` | header, hero info card, sticky bars, footer | ink 74% | ivory 80% | 22px (16px) |
| `glass-3` | modals, drawers, sheets, account menu | ink 93% | ivory 96% | 30px (20px) |

Each level has a 1px hairline border (ivory 12% on dark, ink 12% on light) and a 1px inner top highlight; `glass-2/3` add a soft shadow. The modal scrim is `rgba(4,5,11,.66)` with a 6px blur. Fallbacks: `@supports not (backdrop-filter)` and `prefers-reduced-transparency` switch every level to a solid colour. Scrolling lists (film cards, seats, showtime rows) never carry `backdrop-filter`.

**Theatre backdrop.** Two soft radial pools on a vertical ink gradient: a warm gold glow above the screen (10% alpha dark, 14% light) and a faint dusk glow in the bottom corner. It is static. Poster-tinted hero backdrops are content, not chrome, and keep the film's own colour.

## Layout

- Container max 1280px; gutters 16 / 24 / 32px. Query values: 481, 769, 1025, 1280 (mobile-first, `min-width`).
- Film grid: 2 / 3 / 4 / 5 / 6 columns, posters locked to 2:3.
- Movie detail: one column on phones; from 1025px the poster and facts are sticky on the left and showtimes sit on the right.
- Touch targets are at least 44px. No horizontal page scroll from 360px up (checked at 360px in both themes).
- Seat map: seat size scales between 28 and 40px from the dialog width; halls wider than the dialog pan horizontally inside the map.

## Components

- **Buttons**: four levels. *Primary* (gold gradient pill, ink text, soft gold shadow), *Secondary* (surface pill, border), *Ghost* (text, underline on hover), *Icon* (round surface). Destructive actions are outlined red tertiary buttons. Never two primaries side by side.
- **Header**: UI lockup, nav, and one account control. Language, theme, location, profile, bookings, updates, admin and sign out live in the account menu (popover on desktop, bottom sheet on phones).
- **Chip / Segmented control**: filters, categories, auth tabs, language and theme. Active state is the gold gradient (segmented) or a gold tint with a gold hairline and gold text (chips).
- **Modal / Drawer / Sheet**: one `Modal` component with a focus trap and focus restore. Drawers slide from the right on desktop and rise as bottom sheets on phones.
- **Seat**: number visible in every seat; see the Seats table. Keyboard: arrow keys move, Space selects, only one seat is in the tab order.
- **Ticket summary**: perforated edge, dashed total rule, a "Demo, no real charge" badge, a hold-timer ring that turns red under a minute. The e-ticket QR always sits on white so scanners can read it in either theme.
- **Code input**: four boxes with auto-advance, backspace and paste, set in the numeral face.

## Accessibility

- WCAG 2.1 AA contrast in both themes: every text pair above is at least 4.5:1, and the focus ring and gold hairlines are at least 3:1 against their surfaces.
- `axe-core` (WCAG 2.0/2.1 A and AA rules) reports no violations on home, sign-in, film detail, seat map, checkout, tickets and the operator dashboard, in dark and light, at 1440px and 360px.
- Visible `:focus-visible` rings; QR codes carry an accessible name (never the one-time-secret URI).
- No motion behind content. Everything collapses under `prefers-reduced-motion`; surfaces go solid under `prefers-reduced-transparency`.

## Motion

150-250ms ease-out for state changes, 360ms for modal and sheet entry, a small scale-pop on seat selection, an animated check on success. Exponential ease-out only.
