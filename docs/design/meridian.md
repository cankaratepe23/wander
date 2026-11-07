# Meridian: Wander's design system

Meridian is the design language Wander is built in (chosen in Phase 1a, see `PLAN.md` §4.7). It is crisp, quiet and
precise: neutral surfaces, one cobalt accent and hairline borders, so the ideas, photos and the globe carry the colour.
The code tokens live in `frontend/src/styles/tokens.css`. That file and this doc change together.

Kept for later: [Souvenir](souvenir.md), a redone Postcard direction.

## 1. Principles

1. **Content carries the colour.** The chrome is neutral, and colour means something: the accent marks the one primary
   action, and the four category colours mark the kind of idea.
2. **Hairlines, not shadows.** Use 1 px lines to separate things. A shadow is only for something floating over the map
   (a sheet).
3. **Numbers in mono.** Counts, coordinates, dates and months use Geist Mono, so they line up and read as data.
4. **Every shape means something.** No glows and no gradients. A pin's height is how many ideas it holds, and its colours
   are their categories.
5. **Motion explains where things went.** Every animation answers "where did my idea go?" Nothing loops for decoration.

## 2. Colour tokens

Light and dark are full themes, and the app follows the phone (`prefers-color-scheme`).

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#F6F6F4` | `#0C0C0E` | Page |
| `--surface` | `#FFFFFF` | `#161618` | Cards, sheets, inputs |
| `--text` | `#111113` | `#F3F3F1` | Primary text |
| `--soft` | `#3A3A3F` | `#CFCFD4` | Body copy on cards |
| `--muted` | `#63636A` | `#A1A1A8` | Meta, captions (≥ 4.5:1 on `--bg`) |
| `--line` | `#E4E4E0` | `#2B2B30` | Hairlines, borders |
| `--accent` | `#2F5BFF` | `#7B93FF` | The primary action, the current tab |
| `--on-accent` | `#FFFFFF` | `#0C0C0E` | Text on accent |
| `--accent-soft` / `--accent-ink` | `#E9EEFF` / `#1E3FCC` | `#1E2645` / `#B9C6FF` | Tinted chips, "good" months |
| `--hot` | `#C2410C` | `#FF9A6B` | "Hotspot" labels |
| `--heart` | `#E11D48` | `#FF6B7A` | Hearts |
| `--shadow` | `rgba(17,17,19,.08)` | `rgba(0,0,0,.5)` | Sheets over the map only |

### Category colours

Claude's categories (§4.2 of the plan) fold into four colour families, so the map stays readable:

| Family | Categories | Light | Dark |
|---|---|---|---|
| Food & drink | food, restaurant, market, wine | `#2F5BFF` | `#7B93FF` |
| Nature & outdoors | beach, hiking, nature, ski, road trip | `#12A378` | `#3DD6A3` |
| Stays & experiences | accommodation, wellness, experience | `#8B5CF6` | `#B497FF` |
| Culture & cities | culture, city break, festival, other | `#E8590C` | `#FF8A5C` |

Each has a `-soft` tint for chips (light `#E9EEFF`, `#E5F5EC`, `#F1EBFE`, `#FDEEE4`; dark `#1E2645`, `#12301F`, `#271F3F`,
`#3A2116`) and a `-ink` for text on the tint.

## 3. Type

Geist (UI and display) and Geist Mono, self-hosted variable fonts via Fontsource, latin-ext subset for Turkish.

| Role | Size / line | Weight | Tracking |
|---|---|---|---|
| Display (screen title) | 28 / 1.1 | 640 | −0.035em |
| Title (card, sheet) | 22 / 1.15 | 640 | −0.03em |
| Idea title (idea card) | 30 / 1.08 | 640 | −0.035em |
| Body | 15.5 / 1.5 | 400 | 0 |
| UI (buttons, chips) | 14 / 1 | 600 | 0 |
| Small | 13 / 1.4 | 400–500 | 0 |
| Label (caps) | 12 / 1 | 600 | +0.04em, uppercase |
| Data (mono) | 12 / 1.3 | 400–500 | 0 |

## 4. Space and shape

- **Spacing:** a 4 px scale (4, 8, 12, 16, 20, 24, 32). Screen gutters are 16–22 px.
- **Radii:** 12 px controls (buttons, inputs, icon buttons), 14 px tiles (stat tiles, list items), 22 px sheets and big
  cards, and 999 px chips.
- **Lines:** 1 px `--line`. The selected chip is filled `--text` on `--bg` (inverse), not accent.
- **Hit targets:** at least 40 × 40 px. Primary buttons are 42–50 px tall.
- **Bottom nav:** three tabs (Inbox, Capture, Globe), 84 px including the safe area, with a hairline on top and the
  active tab in `--accent`.

## 5. Motion

| Token | Value | Use |
|---|---|---|
| `--dur-fast` | 160 ms | Press states, chips |
| `--dur-base` | 240 ms | Sheets, tab content |
| `--dur-slow` | 420 ms | The signature moves below |
| `--ease-out` | `cubic-bezier(.2,.8,.2,1)` | Everything that settles |
| Spring | stiffness 380, damping 30 | Piles and tiles (Motion) |

Signature moves:
1. **Save.** The text in the box becomes a card that slides down into the top of the Inbox stack (a shared-element
   `layoutId`), and the box clears for the next idea.
2. **Filed.** When enrichment finishes, the card's status chip changes from "Saved" to its category, and a tile drops
   onto that place's pile on the globe the next time it is shown.
3. **Split and merge.** Zooming the globe splits a pile into child piles, with tiles flying from the parent to the
   children. Zooming out does the reverse.
4. **Glide.** Opening a place flies the globe to it (`flyTo`, 1.2 s) and slides the sheet up.

Everything honours `prefers-reduced-motion`: moves become 120 ms cross-fades.

## 6. The globe and map

MapLibre GL JS 6 in globe projection, using a custom style built on OpenFreeMap vector tiles, with no labels below
country level until zoom 5.

| Layer | Light | Dark |
|---|---|---|
| Ocean / background | `#FFFFFF` | `#141416` |
| Land | `#DCDCD6` | `#2D2D33` |
| Graticule (zoom < 4) | `#EEEEEA` | `#1D1D21` |
| Boundaries (zoom ≥ 3) | `#C9C9C3`, 0.6 px | `#3A3A41`, 0.6 px |
| Labels | Geist 11–13, `--muted`, `--bg` halo | same |
| Sky / atmosphere | off: a flat sphere with a 1 px rim (`#D6D6D0` / `#34343A`) | same |

Region maps (idea card): ocean `#EAF1FB` / `#101826`, land `#FFFFFF` / `#25252A` with a `#D6D6D0` / `#34343A` coast,
and the route as a 2.4 px dotted line in the idea's category colour.

## 7. Piles (the pins)

One isometric tile per idea, coloured by its category family, stacked into a pile per place.

- **Tile:** a 22 × 11 px rhombus top face with a 3.4 px side in the same colour at 62 % brightness, and a 1 px outline in
  the map's ocean colour so tiles separate.
- **Stack:** tiles 3.8 px apart, at most 8 drawn, with ±1.2 px horizontal jitter so it reads as a hand-made pile. Tiles
  are grouped by category, bottom to top.
- **Count:** Geist Mono 11/600 beside the top tile when there are 2 or more ideas.
- **Callouts:** the two biggest visible piles get a hairline leader with the name (Geist 12.5/640) and "N ideas" (mono
  10.5). Leaders shorten, then flip side, to stay on screen.
- **Clustering:** every idea keeps its own geocoded point. MapLibre clusters by screen distance at each zoom (radius
  about 44 px). A cluster sums its category counts and is named by the lowest admin level its members share (city,
  then region, then country), or "Kyoto +2" across borders.
- **Rendering:** piles are HTML markers (SVG inside), which is fine at hundreds of places and lets Motion animate the
  split and merge.

## 8. Key screens

The mockups are the Meridian row of the Phase 1a design canvas.

- **Capture:** a greeting, one big box (text, link or pasted image) that is focused on open, a primary Save button, and
  the recent stack below. Shared-to-app captures land here as "Saved" cards.
- **Inbox:** the stack of all captures and ideas, newest first, with filter chips (All, a category, ♥ Both, Needs a look).
- **Globe:** "Your world", with counts in mono, filter chips, the globe with piles, and a hotspot sheet for the hottest
  region ("Portugal is filling up").
- **Idea card:** a region map with the route, a category chip and its source, the title, the summary, stat tiles
  (length, effort, budget), a 12-month bar, who wants it, then "Chat about this" and "Add to shortlist".
