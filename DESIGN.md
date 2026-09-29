---
name: Parda Cinema
description: A light Uzbek-first cinema programme and seat booking flow.
colors:
  ink: "#252624"
  muted: "#777970"
  paper: "#f8f7f3"
  white: "#fffefa"
  cream: "#efeee9"
  line: "#e5e3db"
  sage: "#52664f"
  sage-light: "#e5ebdf"
  coral: "#c96850"
typography:
  display:
    fontFamily: "Playfair Display, Georgia, serif"
    fontSize: "clamp(3.25rem, 6.2vw, 5.125rem)"
    fontWeight: 500
    lineHeight: 1.02
  body:
    fontFamily: "DM Sans, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.9
rounded:
  sm: "3px"
  md: "5px"
  control: "7px"
spacing:
  xs: "6px"
  sm: "12px"
  md: "20px"
  lg: "32px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.white}"
    rounded: "{rounded.md}"
    height: "47px"
    padding: "0 20px"
  selected-seat:
    backgroundColor: "{colors.sage}"
    textColor: "{colors.white}"
    rounded: "{rounded.control}"
    size: "32px by 29px"
---

# Design System: Parda Cinema

## Overview

**Creative North Star: The Cinema Programme Board**

Parda Cinema is a light repertory programme that carries a visitor from film discovery through local showtime and into a focused auditorium plan. The selected direction adapts the Impeccable assigned textile itinerary seed to a clear cinema programme board, in keeping with the requested lighter interface. The first viewport presents the programme and the next useful booking action without demanding payment.

The interface is Uzbek-first, priced in UZS, and uses `Asia/Tashkent` for dates and times. Its film posters are composed from CSS color fields and linework; no external film artwork is presented as licensed cinema content.

**Key Characteristics:**
- Editorial film typography with practical sans-serif controls
- Warm light surfaces and muted sage availability states
- Clear separation between film, screening, seat map, and booking summary
- No-charge demo confirmation with an explicit ten-minute hold

## Colors

Warm ivory and ink form the reading surface; sage describes seat availability and coral is a restrained accent.

### Primary
- **Muted Sage** (`#52664f`): Available seat, location, and positive selection context.
- **Cinema Coral** (`#c96850`): Small time-sensitive accents.

### Neutral
- **Near-Black Ink** (`#252624`): Main text and primary action.
- **Quiet Gray** (`#777970`): Secondary interface copy.
- **Warm Paper** (`#f8f7f3`): Main page and dialog background.
- **Soft White** (`#fffefa`): Inputs, showtime chips, and inset surfaces.
- **Programme Cream** (`#efeee9`): Date rail and supporting bands.
- **Fine Divider** (`#e5e3db`): Rules, outlines, and separation.
- **Sage Tint** (`#e5ebdf`): Light selection surfaces.

## Typography

**Display Font:** Playfair Display (with Georgia, serif)
**Body Font:** DM Sans (with sans-serif fallback)

**Character:** Film titles use an editorial serif; booking controls remain direct and highly legible in a neutral sans-serif.

### Hierarchy
- **Display** (500, responsive 52–82px, 1.02): Landing statement and film feature hierarchy.
- **Headline** (500, 26–42px): Programme sections, films, and dialog titles.
- **Title** (500–600, 17–20px): Cards, steps, and admin subheads.
- **Body** (400, 11–13px, 1.65–1.9): Supporting copy and booking details.
- **Label** (600–700, 8–10px, spaced capitals): Metadata, field context, and section labels.

## Layout

The desktop page uses a centered 1440px maximum width and a two-column opening composition. Film rows pair a compact poster with metadata and showtimes. At 650px and below, the hero stacks and film rows narrow while preserving readable title and seat controls. The auditorium plan scrolls horizontally within its dialog on small screens; booking totals and actions stay in the dialog footer.

## Elevation & Depth

The programme relies primarily on fine borders and tonal surface changes. Shadows are reserved for the hero ticket and active dialog, so overlays remain distinct from the page.

## Shapes

Most cards and controls use restrained 3–7px corners. Seat shapes use a slightly taller top edge through a 7px/7px/4px radius to read as seats. Seat states use both text legend labels and distinct fill/border combinations.

## Components

- **Primary button:** Ink fill, white label, compact rectangular silhouette; sage hover.
- **Showtime chip:** White inset surface with local time first and auditorium below.
- **Seat:** Available sage tint; premium warm tint; selected sage; unavailable neutral gray. Every seat has an accessible row/number label.
- **Booking summary:** Names film, local time, seats, price, and hold state before no-charge confirmation.
- **Dialog:** Focused seat selection, authentication, or confirmation; closes explicitly and allows a visible recovery path.

## Do's and Don'ts

- Keep UZS price and Tashkent-local showtime visible before confirmation.
- Explain that the map is live but a seat is not reserved until the server accepts the hold.
- Preserve distinct labels for available, selected, premium, and unavailable seats; color alone is insufficient.
- Keep sample films clearly fictional and the payment step explicitly no-charge.
- Don't imply a payment was collected or that fictional screening data is a live cinema catalogue.
- Don't use dark, heavy theatre styling that conflicts with the requested light visual direction.
