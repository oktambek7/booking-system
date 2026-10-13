---
name: Parda Cinema
description: An Uzbek-first cinema booking experience built from frosted glass over a drifting aurora, dark by default.
colors:
  bg: "#0a0a18"
  bg-elevated: "#12122a"
  aurora-violet: "#7c5cff"
  aurora-magenta: "#ff3d8b"
  aurora-cyan: "#22d3ee"
  aurora-amber: "#ffb547"
  text: "#f5f5ff"
  text-2: "#b4b4d0"
  text-3: "#a0a0c0"
  action-from: "#7653f8"
  action-to: "#d61f6e"
  seat-available: "#34d399"
  seat-selected: "#7653f8"
  seat-premium: "#ffb547"
  seat-taken: "#5b5b78"
  success: "#22c55e"
  warning: "#f59e0b"
  danger: "#f43f5e"
  light-bg: "#f6f5ff"
  light-text: "#14142b"
  light-text-2: "#4a4a68"
typography:
  display:
    fontFamily: "Unbounded Variable, system-ui, sans-serif"
    fontSize: "clamp(1.75rem, 1.1rem + 3vw, 3.5rem)"
    fontWeight: 600
    lineHeight: 1.15
  body:
    fontFamily: "Manrope Variable, system-ui, sans-serif"
    fontSize: "0.9375rem (15px) on phones, 1rem from 769px"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "Manrope Variable, system-ui, sans-serif"
    fontSize: "0.75rem (12px, the floor)"
    fontWeight: 700
rounded:
  sm: "10px"
  md: "16px"
  lg: "24px"
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
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
    height: "48px"
  chip:
    backgroundColor: "glass-1"
    rounded: "{rounded.pill}"
    height: "40px"
  seat:
    size: "28-40px, scales with the hall width"
    rounded: "9px 9px 5px 5px"
---

# Design System: Parda Cinema

## Overview

**Creative North Star: Aurora Glass Cinema**

Soft coloured light drifts behind frosted-glass panels, like light thrown from a cinema screen. The page is eye-catching while you browse films and calm while you choose seats: glass carries the interface, solid colour carries meaning. Dark ("Night Screen") is the default because glass needs a coloured field behind it and a darkened room is where people book. A light theme ("Matinee") shares every token.

The interface is Uzbek-first with Russian and English, prices in UZS, times in `Asia/Tashkent`. Film and showtime data comes from Cinematica and TMDB; checkout is a demo that never charges money.

**Key Characteristics:**
- Three glass levels only, over four large blurred colour fields
- One gradient primary action per screen, always in the same place
- Seat state told three ways: colour, pattern/icon, and text
- Four breakpoints, 8px spacing grid, nothing under 12px

## Colors

### Aurora (identical in both themes)
- **Violet** `#7c5cff`, **Magenta** `#ff3d8b`, **Cyan** `#22d3ee`, **Amber** `#ffb547`. They live in the background fields and in small highlights (active nav underline, selected states, glow). They are not used as text on glass.

### Night Screen (default)
- **Base** `#0a0a18`, **Elevated** `#12122a`.
- **Text** `#f5f5ff`, **Secondary** `#b4b4d0`, **Tertiary** `#a0a0c0` (metadata only).
- **Primary action**: a gradient from `#7653f8` to `#d61f6e` with white text. Both stops are deeper than the brand violet `#7c5cff` and magenta `#ff3d8b` so white text keeps at least 4.5:1 (4.8 and 4.9); the bright brand colours stay for the background fields, glow and accents.

### Matinee (light)
- **Base** `#f6f5ff` with pastel violet, pink and cyan fields. **Text** `#14142b`, **Secondary** `#4a4a68`. The action gradient runs `#6a45f5` to `#c21a64`.

### Semantic (solid, never glass)
- Seat available `#34d399`, selected `#7653f8`, premium `#ffb547`, taken `#5b5b78` with a diagonal hatch. Success `#22c55e`, warning `#f59e0b`, danger `#f43f5e`.

## Typography

**Display:** Unbounded (600), self-hosted through Fontsource, for film titles and headings.
**Body/UI:** Manrope (400-700), self-hosted. Both carry Latin (including the Uzbek `oʻ`/`gʻ` modifier letter), Cyrillic, and Vietnamese subsets with `font-display: swap`.

- Display `clamp(1.75rem, 1.1rem + 3vw, 3.5rem)` for hero titles (long film titles need room; the token for generic display is `clamp(2.5rem, 1.6rem + 3.6vw, 4.5rem)`), H2 28-44px, H3 20-24px, body 15-16px, small 13px, label 12px (uppercase, +0.08em).
- Tabular numerals for times, prices and seat numbers. No kicker or eyebrow above headings.

## Glass

| Level | Used for | Fill | Blur |
|---|---|---|---|
| `glass-1` | cards, chips, filter panel, inputs' neighbours | white 6% (dark) / 55% (light) | 16px (10px on phones) |
| `glass-2` | header, hero info card, sticky bars, footer | deeper tint, 62-72% | 24px (16px) |
| `glass-3` | modals, drawers, sheets, account menu | 84-90% | 32px (20px) |

Each level has a 1px border (white 12%), a 1px inner top highlight, and `glass-2/3` add a soft shadow. Scrim behind modals is `rgba(5,5,15,.6)` with a 6px blur. Fallbacks: `@supports not (backdrop-filter)` and `prefers-reduced-transparency` switch every level to a solid elevated colour. Scrolling lists (film cards, seats, showtime rows) never carry `backdrop-filter`.

The background is four radial-gradient fields (no `filter: blur`) drifting on a 44-60s loop, static under `prefers-reduced-motion`.

## Layout

- Container max 1280px; gutters 16 / 24 / 32px. Query values: 481, 769, 1025, 1280 (mobile-first, `min-width`).
- Film grid: 2 / 3 / 4 / 5 / 6 columns, posters locked to 2:3.
- Movie detail: one column on phones; from 1025px the poster and facts are sticky on the left and showtimes sit on the right.
- Touch targets are at least 44px. No horizontal page scroll from 320px up.
- Seat map: seat size scales between 28 and 40px from the dialog width; halls wider than the dialog pan horizontally inside the map.

## Components

- **Buttons**: four levels. *Primary* (gradient pill with a soft coloured shadow), *Secondary* (glass pill, border), *Ghost* (text, underline on hover), *Icon* (round glass). Destructive actions are outlined red tertiary buttons. Never two primaries side by side.
- **Header**: logo, nav, and one account control. Language, theme, location, profile, bookings, updates, admin and sign out live in the account menu (popover on desktop, bottom sheet on phones).
- **Chip / Segmented control**: filters, categories, auth tabs, language and theme. Active state is the action gradient or a violet tint.
- **Modal / Drawer / Sheet**: one `Modal` component with a focus trap and focus restore. Drawers slide from the right on desktop and rise as bottom sheets on phones.
- **Seat**: number visible in every seat. Selected seats show a check and a glow, taken seats a hatch pattern, premium seats an amber fill with a corner dot. Keyboard: arrow keys move, Space selects, only one seat is in the tab order.
- **Ticket summary**: perforated edge, dashed total rule, a "Demo, no real charge" badge, a hold-timer ring that turns red under a minute.
- **Code input**: four boxes with auto-advance, backspace and paste.

## Motion

150-250ms ease-out for state changes, 360ms for modal and sheet entry, a small scale-pop on seat selection, an animated check on success. Exponential ease-out only. Everything collapses under `prefers-reduced-motion`.

## Do's and Don'ts

- Do keep the UZS price and Tashkent-local showtime visible before confirmation.
- Do keep one primary action per screen in the same spot (mobile: the sticky bottom bar).
- Do keep seat state distinguishable without colour.
- Don't put gradient on text, or text below 12px.
- Don't stack more than the three glass levels, or blur a scrolling list item.
- Don't imply a real charge: checkout stays labelled as a demo.
