# Souvenir: a design language kept for later

Souvenir is a redone take on Phase 1a's Postcard direction. It was the favourite look, but we're building
[Meridian](meridian.md) first. It is written down here so it can come back, possibly as a second theme. Because both
use the same token names, Souvenir would mostly be a swap of `tokens.css`, the fonts and the pile renderer.

## The idea

Copy one real object, not a mood: the mid-century large-letter **"Greetings from…" postcard**. Big block letters with a
printed 3D edge, three flat print inks on warm white paper, a sky-blue sea, and the back of a postcard for details.
The first Postcard attempt (sand, terracotta, a soft serif, sticker pins) failed because it was a generic "warm travel"
mood.

## Tokens

| Token | Value | Use |
|---|---|---|
| Paper | `#FAF7F0` | Page |
| Card | `#FFFDF8` | Postcard backs, piles |
| Ink | `#1A1A1A` | Text, 1.5 px borders, the letter edge |
| Tomato | `#E8442E` | Primary action, script lines, best months |
| Teal | `#0E5E6F` | Headlines, handwritten notes |
| Sunflower | `#F4B400` | "Good" months, stamps |
| Sky | `#A9D8E8` | Sea on maps |
| Pale sky | `#7FC6E8` | Fourth category |
| Land | `#FDFBF5` with an ink coastline | Maps |

Categories: tomato, teal, sunflower and pale sky. Dark mode is not designed yet. One option is "night print", ink-blue
paper with the same inks.

## Type

- **Bowlby One** for large letters: uppercase, filled with three hard ink bands (sunflower to 42 %, tomato to 68 %,
  teal below) over a 4–5 px solid ink extrusion. Build it with two stacked layers: the extrusion as a `text-shadow` on a
  plain copy behind, and the banded fill clipped to the text in front.
- **Yellowtail** for the "Greetings from" script, rotated −5°.
- **Libre Franklin** for UI and reading, with 800 uppercase and +0.1em tracking for buttons and labels.
- **Caveat** only for notes one of you wrote to the other.

## Shapes and details

- Postcard backs: 1.5 px ink border, a 3 px radius, rotated −1.2° when floating. The back has a vertical divider, a
  stamp box at the top right (category colour with a dotted perforated outline) and ruled address lines carrying
  facts.
- A postmark circle (place, date, source) overlapping the stamp.
- Buttons: square, 1.5 px ink border, solid ink or tomato.
- A halftone dot patch (a 7 px grid of tomato dots at 35 %) is the only texture, used once per screen at most.
- Months: 12 ink-outlined cells, tomato for best and sunflower for good.

## Piles

Tiny postcards (21 × 14 px, paper fill, 0.9 px ink outline, a category-coloured stamp corner and two address lines on
the top card), each tilted a few degrees as if dropped, 2.8 px apart. They have the same clustering, counts and
callouts as Meridian.

## Mockups

The "Souvenir" screens (Globe, Idea card) in row 2 of the Phase 1a design canvas. Its sibling takes, Airmail and Ticket,
are there too.
