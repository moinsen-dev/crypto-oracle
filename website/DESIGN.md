---
name: CryptoOracle public notebook
description: A printed research notebook — warm paper, deep green ink, serif headlines, monospaced field labels.
colors:
  primary:    "#203B34"   # ink: headlines and body text
  secondary:  "#5D6B62"   # muted: supporting text, captions, axes
  tertiary:   "#173F36"   # deep green: primary button, dark teaser panel
  neutral:    "#F5F4EE"   # paper: page background
  surface:    "#FFFEFA"   # cards, figures, tables
  surfaceAlt: "#E8EDDF"   # field-note card, callouts, journal results
  border:     "#D8DDD0"   # hairlines
  accent:     "#A4482B"   # rust: a result that went against the model
  highlight:  "#DBEAB4"   # lime: light button on the dark panel, selection
  emphasis:   "#537845"   # italic words in headlines
  success:    "#2F6B4F"   # chart line or number that held up
  error:      "#922D24"
  info:       "#1755A1"   # frozen forecast line in the journal
  warning:    "#B45313"   # observed price line in the journal
typography:
  h1:         { fontFamily: Georgia, fontSize: 5.7rem,  fontWeight: 400, lineHeight: 0.99, letterSpacing: -0.055em }
  h2:         { fontFamily: Georgia, fontSize: 2.9rem,  fontWeight: 400, lineHeight: 1.12, letterSpacing: -0.04em }
  h3:         { fontFamily: Inter,   fontSize: 1.12rem, fontWeight: 600, lineHeight: 1.12, letterSpacing: -0.025em }
  body-md:    { fontFamily: Inter,   fontSize: 1rem,    fontWeight: 400, lineHeight: 1.65 }
  body-sm:    { fontFamily: Inter,   fontSize: 0.85rem, fontWeight: 400, lineHeight: 1.65 }
  label-caps: { fontFamily: ui-monospace, fontSize: 0.75rem, fontWeight: 500, lineHeight: 1.6, letterSpacing: 0.13em }
  data:       { fontFamily: ui-monospace, fontSize: 0.875rem, fontWeight: 400, lineHeight: 1.5 }
rounded: { sm: 2px, md: 4px, lg: 5px, full: 30px }
spacing: { xs: 8px, sm: 14px, md: 25px, lg: 38px, xl: 55px, 2xl: 82px }
---

## Visual Theme & Atmosphere

A research notebook that happens to be a website. Warm paper, one deep green, generous white space, hairlines instead of boxes. Headlines are set in a light serif and speak in short sentences; labels are small monospaced capitals, like stamps on a field note. Nothing glows, moves or sells. The calm is the point: the content is often a result that went against us.

## Color Palette & Roles

- **Ink `#203B34` on paper `#F5F4EE`** carries almost everything. Muted `#5D6B62` is for supporting text only.
- **Deep green `#173F36`** fills the one primary button per region and the dark paper-portfolio panel. Lime `#DBEAB4` appears only on that panel and in text selection.
- **Emphasis green `#537845`** colours the italic words in a headline, one phrase at most.
- **Rust `#A4482B`** marks a result where the model lost (bars `#C98A72`). Green `#456E55` / `#2F6B4F` marks what held up. Never decorate with either.
- **Journal lines:** blue dashed `#1755A1` is always the frozen prediction, orange solid `#B45313` always the observed price.
- **Portfolios:** blue/circle/solid, orange/square/dashed, violet/triangle/dotted. Colour is never the only carrier; keep the marker and dash pattern.

## Typography

- System stack only: Inter or the platform sans, Georgia, the platform monospace. No web fonts, no external requests.
- No HTML text below 12px (`.75rem`). Labels, pills, table heads and footers included; `scripts/type-floor.test.mjs` fails the check otherwise. Text inside SVG charts is sized in chart units and is the only exception.
- Headlines: Georgia, weight 400, tight tracking, often broken by hand with `<br />`. An `<em>` inside turns green italic.
- Eyebrows and field labels: monospace capitals at 0.13em tracking, e.g. `FIELD NOTE / 002`.
- Numbers that are the result of a study are set large in the serif; identifiers and hashes in monospace.

## Spacing & Layout

- One centred column, `min(1180px, 100% - 96px)`; 64px side total below 1050px, 40px below 760px.
- Sections are separated by 82px (55px on phones) and hairlines, not by coloured bands.
- Reading pages use a 235px sticky contents rail plus one text column; the rail becomes an inline list on phones.
- The menu replaces the six-entry navigation below 900px; the single-column layout starts at 760px.

## Components

- **button:** deep green fill, 4px radius, label plus an arrow glyph. `button-light` is lime and lives only on the dark panel.
- **text-link:** 600 weight with a 1px ink underline and an arrow; the default way to move on.
- **field-note card:** `surfaceAlt` fill, offset flat shadow, mono header row with number and date.
- **figure / benchmark card:** `surface` fill, 1px border, 5px radius, mono chart label row on top, fine print below.
- **callout:** `surfaceAlt` fill with a 3px green left rule, headed “What we take from it”.
- **tag / pill:** tiny monospace status such as `Implemented` or `Historical · exploratory`.
- **tables:** hairline rows inside a focusable horizontal scroll region, caption on top.
- **charts:** inline SVG drawn at build time or by the page’s own script. Dashed grid `#E3E6DD`, mono axis labels, every chart has a `<title>`, a `<desc>` with the numbers, and its data in a table or download.

## Voice & Tone

- Plain, short, first person plural. State what was measured, then what it does not show.
- Lead with the result even when it is unflattering: “The simple baseline won.”
- No promises, no signals, no urgency. “Suggestive” and “not established” are normal words here.
- Every number names its unit and sample; every page names its measurement date.

## Do / Don't

- ✓ One headline number per card, with the sentence that limits it directly underneath.
- ✗ A percentage without its sample size and period.
- ✓ Rust for “went against the model”, green for “held up”.
- ✗ Red/green as profit/loss decoration, tickers, or anything that reads as a trading call.
- ✓ Same-origin assets only; scripts limited to the allowlisted files in `public/scripts/`.
- ✗ Inline scripts, web fonts, embeds, analytics, cookies.

## Accessibility Notes

- Focus ring: 3px `#AB512E` with 5px offset on every interactive element; skip link first in the tab order.
- Measured contrast: ink on paper 11.0:1, muted `#5D6B62` on paper 5.1:1 (5.6:1 on surface), rust 5.9:1 and success green 6.2:1 on surface, button label 11.6:1. Emphasis green `#537845` is 4.6:1 — headlines only.
- Charts ship a narrow drawing for phones instead of scaling text down, and never rely on colour alone.
- Motion is limited to hover transitions and smooth scrolling, both disabled under `prefers-reduced-motion`.
