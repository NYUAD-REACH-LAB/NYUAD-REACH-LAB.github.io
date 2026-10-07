# REACH Lab website — design

The public site of **REACH Lab — Robot Learning and Control Lab**, New York University Abu Dhabi.
This document is the reference for anyone changing how the site looks or reads. The build, the data
schema and deployment are in `README.md`.

The site sits beside the PI's personal site (https://abudakka.github.io) and shares its tone:
calm, academic, serif headings over a plain sans body, light and dark. It does not share its look.
Where the personal site is a list of one person's work, the lab site leads with the invitation to
join, then the research, then the people, as a lab's front door should.

## Change log

| Date | Change |
|---|---|
| 2026-09-13 | First design (Milestone 1): typographic wordmark with a drawn mark; violet/copper palette on warm paper; all artwork built from sphere geometry. |
| 2026-09-13 | **Brand rebase** (Fares, Milestone 2 review). The logo of record (`lab/brand/nyuad-variants/logo-nyuad-B-violet-oasis*.png`) replaces the typographic wordmark and the drawn mark; the favicon is the logo's arm. The palette moves to the NYU Abu Dhabi brand: NYU Violet for headlines and ink, Oasis as the single accent (was violet), Dark Violet 1 as the dark ground, Violet 4 and Turquoise Sea as the accents on dark; the copper second hue is retired. Artwork recoloured. Fields 2–7 redrawn as pictures of the field itself (no sphere unless the field is about geometry); field 1 and the home hero keep their spherical construction. The field 6 name now appears on the site (leak-test exception for the exact phrase "decision-making"). |

---

## 1. Identity

### The logo

- **Logo of record:** variant B, *violet-oasis* — `REACH` in NYU Violet `#57068c`, the robot arm in
  Oasis `#008ba9`, subtitle `ROBOT LEARNING AND CONTROL LAB` in Dark Violet 1. On dark grounds, the
  `-dark` file: letters Violet 4, arm Turquoise Sea, subtitle white.
- **Files:** the originals are copied from `lab/brand/nyuad-variants/` into `src/brand/` and never
  linked from outside the site. `src/brand/web/` holds the web derivatives (`logo.png`,
  `logo-dark.png` at 144 px tall; `favicon-32.png` and `apple-touch-icon.png`, the arm alone on a
  transparent square). The build copies them to `assets/` and warns if `src/brand/` drifts from the
  records' copy.
- **Use:** header (64 px tall; 44 px below 480 px) and footer (72 px). Both images are in the page;
  the stylesheet shows the one that matches the theme, including the manual toggle. Alt text is the
  lab's full name.
- **Rules (from `lab/brand/README.md`):** use the logo as supplied — no recolouring beyond the dark
  variant, no stretching, no cropping of the arm. The favicon is the one sanctioned derivative: the
  *whole* arm, isolated, scaled.
- In running text the name is "REACH Lab"; the expansion lives in the logo and in page titles. Never
  set REACH in lowercase, never expand it into words.

### Voice

- **Plural and plain.** "We", present tense, short sentences. The lab speaks; individuals are named
  when they did something.
- **Precise, not promotional.** No "cutting-edge", "world-class", "revolutionary". A claim appears
  only if a record supports it; a number only if a record carries it.
- **Say what happened, not what is pending.** News reports finished public events. Nothing that
  is still under way appears.
- **Invite, don't advertise.** The join text welcomes enquiries and says exactly what to send. It
  never implies an open position that no record names.
- Titles of papers are quoted exactly; venues as the publication record gives them.
- Field phrasing is the PI's own and is not edited.

---

## 2. Colour

Two palettes, switched by the system setting or the theme button (stored per browser). All
colours are CSS custom properties in `src/assets/site.css`; nothing else hard-codes a colour.
Brand names are from the NYU Abu Dhabi brand guidelines (Sept 2023), as recorded in
`lab/brand/README.md`.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--paper` | `#ffffff` white | `#1a022a` Dark Violet 1 | page ground |
| `--surface` | `#ffffff` white | `#2b0346` Dark Violet 2 | cards, art frames |
| `--surface-2` | `#f4f2f6` ¹ | `#2b0346` Dark Violet 2 | alternate sections, footer, filter panel |
| `--heading` | `#57068c` NYU Violet | `#cdb5dd` Violet 4 | headlines, paper titles, names |
| `--ink` | `#57068c` NYU Violet | `#ffffff` white | body text |
| `--muted` | `#5f5b66` ¹ | `#b9b3c2` ¹ | secondary text, captions, artwork grids |
| `--faint` | `#6e6a75` ¹ | `#a39cad` ¹ | dates, eyebrows, role lines |
| `--line` | `#dcd9e0` ¹ | `#3d0462` Dark Violet 3 | rules and borders (never text) |
| `--accent` | `#008ba9` Oasis | `#7fbec6` Turquoise Sea | the single accent: primary buttons, link underlines, focus rings, current-page marks, the accent path in artwork |
| `--on-accent` | `#1a022a` Dark Violet 1 | `#1a022a` Dark Violet 1 | text on the accent |
| `--link` / `--link-hover` | NYU Violet / Dark Violet 1 | Turquoise Sea / Violet 4 | link text |
| `--art-ink` | NYU Violet | Violet 4 | ink strokes in artwork, boundaries and limits |
| `--band` / `--on-band` | NYU Violet / white | Dark Violet 2 / white | the "Work with us" band |

¹ **Provisional neutrals.** The guidelines' neutral greys were not available in the records when
this was built; these values are neutral placeholders chosen for contrast. Replace them with the
guideline greys (tokens `--surface-2`, `--muted`, `--faint`, `--line`) and re-check the table below.

**Oasis on light is not a text colour.** At 4.0:1 on white it passes for graphics, focus rings and
large text but not for body text, so in light mode links are NYU Violet with an Oasis underline, and
the Oasis button carries Dark Violet 1 text (4.8:1). On dark, Turquoise Sea is a full text colour.

### Contrast (WCAG 2.1, text pairs actually used)

| Pair | Light | Dark |
|---|---|---|
| heading on paper | 11.6 | 10.4 |
| heading on surface-2 | 10.4 | 9.3 |
| ink on paper | 11.6 | 19.3 |
| ink on surface-2 | 10.4 | 17.4 |
| muted on paper | 6.6 | 9.5 |
| muted on surface-2 | 5.9 | 8.5 |
| faint on paper | 5.3 | 7.3 |
| faint on surface-2 | 4.7 | 6.6 |
| link on paper | 11.6 | 9.3 |
| link on surface-2 | 10.4 | 8.4 |
| on-accent on accent (buttons, award tag) | 4.8 | 9.3 |
| accent on paper (non-text only in light) | 4.0 | 9.3 |
| on-band on band, and the inverted band button | 11.6 | 17.4 |

Every text pair clears AA (4.5:1). `faint` is for text of 0.78 rem and up that is never the only
carrier of information.

---

## 3. Type

No web fonts are loaded: nothing is fetched from third parties (the Contact page map is the one exception) and every page stays light. The
stacks pick the best serif and sans each platform already has.

| Role | Stack | Weight |
|---|---|---|
| Headings, paper titles, monograms | `"Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", "URW Palladio L", P052, Georgia, serif` | 600 |
| Body, navigation, buttons | `system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans", Arial, sans-serif` | 400 / 600 |
| Dates, eyebrows, kinds, link badges, role lines | `ui-monospace, "SF Mono", "Cascadia Mono", "Roboto Mono", Menlo, Consolas, monospace` | 400 |

Scale — major third (×1.25) from 16 px, the top three steps fluid:

| Token | Size | Use |
|---|---|---|
| `--step--1` | 14 px | small print |
| `--step-0` | 16 px | body, line-height 1.6 |
| `--step-1` | 20 px | lede, card titles, h3 |
| `--step-2` | 25 px | PI name, field names on the research index |
| `--step-3` | 25.6 → 31 px | h2 |
| `--step-4` | 31 → 39 px | h1 on inner pages |
| `--step-5` | 35 → 49 px | home headline, field titles |

Rules: one h1 per page; headings balance their lines; body measure ≤ 68 ch; eyebrows are mono,
uppercase, tracked `+0.12em`, and always sit directly above a heading.

---

## 4. Grid and spacing

- **Container:** 72 rem (1152 px) max, side gutter `clamp(16px, 4vw, 40px)`. Works from 360 px.
- **Columns:** CSS grid, not a fixed column count. Two-up splits (hero, news/publications, people
  teaser, field header) break at 56 rem; three-up join cards at 48 rem; research tiles use
  `auto-fill` with a 15.5 rem minimum (four across on desktop: seven fields sit 4 + 3), person
  cards 22 rem.
- **Spacing scale:** 4 · 8 · 12 · 16 · 24 · 32 · 48 · 72 px (`--space-1` … `--space-8`). Sections are
  72 px apart vertically, sub-sections 48 px.
- **Radius:** 6 px on cards and frames; pill (999 px) on buttons, chips and filter options.
- **Rules over boxes:** lists (news, publications, alumni, resources, contact) are separated by
  1 px rules, not cards. Cards are kept for things you might click as a whole (fields, people).

---

## 5. Components

| Component | Notes |
|---|---|
| **Header** | Logo left, navigation right, theme button. Below 64 rem the navigation collapses behind a Menu button (JavaScript); without JavaScript it stays visible as a wrapped list. Current page: Oasis underline + `aria-current`. Pages that are not built (Teaching, while it has no courses) are simply absent. |
| **Hero** (home) | Eyebrow (affiliation), headline, mission paragraph, two buttons: *Join the lab* (primary) and *Our research*. Artwork on the right; above the text on small screens. |
| **Band** | The one full-bleed coloured section: "Work with us" on the home page, straight after the hero. Three audience columns with an accent top rule, one inverted button. |
| **Buttons** | Pill, 44 px tall minimum. Primary = accent fill with Dark Violet 1 text; secondary = heading-colour outline. One primary per section. |
| **Field tile** | Artwork thumbnail, title, the one-sentence summary; the whole tile is the link. |
| **Field row** (research index) | Framed artwork, field name, summary, counts of people and publications. |
| **Chip** | Pill link to a research field; small variant on people and publications. |
| **News item** | Mono date column (day precision when known, else month or year), kind tag (`paper`, `talk`, `people`, `lab` outlined in accent; `award` filled), one sentence, optional DOI/arXiv link. |
| **Publication** | Serif title, italic venue, authors with the PI in bold, link badges (mono), field chips. `data-fields` carries field numbers for the filter. Preprints carry a "Preprint" label. On the publications page a "Copy BibTeX" button (added by JavaScript, so absent without it) copies the entry's BibTeX from a hidden `<pre data-bib>`. |
| **Publication filter** | Radio pills per field with counts, and a live count. Hidden until JavaScript runs; the full list, grouped by year, reads without it. |
| **Person card** | Photo (or monogram) at 12rem square, name, role · since year (mono), one-line topic, the member's bio, field chips; the text runs to the right of the photo and continues below it; on phones the photo sits above the text. |
| **PI card** | Large monogram, name, role and title, personal website and email. Accent rule on top. |
| **Monogram** | Initials in the serif inside a ring; a short accent arc and tangent whose angle is derived from the person's id, so every member has a stable, distinct mark. Used until a member's photo is supplied. |
| **Checklist** (join) | Numbered rows with an accent tick: what to put in the email. |
| **Contact list** | Label (mono, uppercase) / value rows. |
| **Footer** | Logo, full name and affiliation, email, lab GitHub, PI site, page links, year. |

Interaction: links thicken their underline on hover, focus is a 3 px accent outline everywhere, and
the skip link is the first focusable element on every page.

---

## 6. The artwork

Every image on the site is drawn in code by `build.py` and inlined as SVG, so it follows the theme
and weighs a few kilobytes. There are two families with one line style.

### Line style (all artwork)

| Class | Stroke | Meaning |
|---|---|---|
| `a-acc` | accent, 2.5 px, round caps | **the one bold path** — the skill, the trajectory, the chosen branch, the signal, the force |
| `a-ink` | art-ink, 1.25 px (1 px thin, 2.25 px fingers) | the thing drawn: bodies, demonstrations, fingers, springs |
| `a-limit` | art-ink, 1.75 px, dashed when it is a boundary | limits and feedback: forbidden regions, safe-set edges, contact normals, closing arrows |
| `a-grid` / `a-hatch` | muted, 0.75 px | context: level curves, grids, ground and object hatching |
| `a-band` | accent fill 16 % | the spread around the bold path (variance, chosen cone) |
| `a-cone` | muted fill 10 % | spread around the paths not taken |
| `a-plane` | accent fill 12 %, 1 px edge | tangent planes (geometric artwork only) |
| dots | art-ink (start, joints) · accent with a paper halo (goal, equilibrium, tip) | |

### Rules

1. **One accent path per artwork.** Everything else is art-ink, muted context, or fills.
2. **Draw the field, not a metaphor for it.** A manifold, geodesic or tangent plane appears only
   where the field is about geometry (field 1, and the home hero, which stands for the lab).
3. **No text, no photographs, no faces** inside artwork. Hands and arms are drawn as mechanisms
   (outlines, jointed chains), never as people.
4. **Strokes do not scale** (`vector-effect: non-scaling-stroke`), so the same drawing reads at card
   size (≈ 250 px wide) and at field-header size (≈ 520 px).
5. **Deterministic.** The same data produce the same bytes; the few noisy elements use a fixed-seed
   generator.
6. **Accessible.** Artwork carrying meaning has `role="img"` and an `aria-label` describing what is
   drawn (text in `data/research.json`); thumbnails next to a visible title are `aria-hidden`.
7. **Motion is optional.** The hero geodesic draws itself once, only when the visitor has not asked
   for reduced motion.

### Per image

| Image | Drawing |
|---|---|
| Home hero | a sphere with latitude/longitude grid; a geodesic between two points; tangent planes at both ends; a fan of geodesics leaving the start (the exponential map); the log-map arrow; a normal at the goal; the dotted flat chord |
| 1 Geometric and Riemannian robot learning | sphere; geodesic; tangent plane with the log-map arrow; a vector parallel-transported along the path; the chord |
| 2 Safe and certifiable learning-based control | a bowl seen from above as nested level curves; a trajectory spiralling inward to the equilibrium, bending away from a hatched forbidden region with a dashed boundary |
| 3 Learning from demonstration and physical interaction | thin demonstrated strokes inside a shaded variance band converging into one bold reproduced motion; a guiding arrow at the start; a target ring at the goal |
| 4 Compliant and contact-rich manipulation | a fingertip pressing a surface that dents under it (compression arcs, ground hatch); the contact force arrow; a spring and a damper in parallel between a fixed support and the finger |
| 5 Soft and continuum robotics | a tapered continuum arm rising from a hatched base and wrapping around a round object: outline, cross-section rings, bold backbone, tip dot |
| 6 Decision-making under uncertainty | a fan of candidate futures from one point, each in a widening cone; one bold chosen branch with its narrower accent cone |
| 7 Neural interfaces and assistive robotics | a forearm with two electrodes; the EMG trace rising and running to a hand whose fingers flex from their extended (ghost) pose; a dashed arrow from the hand back to the arm closes the loop |

New artwork (a future field, a project page) uses the same line style and rules.

---

## 7. Imagery beyond the artwork

No stock photography, no AI-generated people, no photos of anyone until the lab provides them with
the person's consent. Members get the generated monogram. When photos arrive they replace the
monogram, square, with the person's name as alt text — 12rem on the People page cards, the monogram's own
size elsewhere.

---

## 8. Accessibility, performance, print

- Semantic landmarks (`header`, `nav`, `main`, `footer`), one h1, headings in order, lists as lists.
- WCAG AA contrast in both themes (§2); 44 px touch targets; everything keyboard reachable;
  visible focus; skip link.
- JavaScript only for the theme button, the mobile menu, the publication filter and the Copy BibTeX buttons. Every page is
  complete without it.
- No page over 300 KB with its CSS and JavaScript (images excluded); logos are 144 px-tall PNGs
  of about 30 KB; no third-party requests, with one exception: the Contact page's small map window is a lazy-loaded Google Maps frame (`map_embed_url`), and clicking it opens Google Maps in a new tab.
- Print: navigation, buttons, filter and artwork are hidden; colours go to black on white; the light
  logo prints; cards do not break across pages; a filtered publication list prints in full.
- Every link and asset path is relative, so the site works at a sub-path and on a custom domain.
