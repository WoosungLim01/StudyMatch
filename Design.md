# StudyMatch Design System

> **Product name: StudyMatch.** Use exactly this spelling everywhere users or
> readers see it: `<title>` tags, the header brand, headings, body copy, docs.
> Do not use "StudyNest" (a wrong name from an early brief) or any other variant.

The visual language for every StudyMatch screen — login, survey, home/matching,
profile setup, chat, admin. The pages in `ui/` are plain HTML/CSS/JS, so this
doc is written as copy-pasteable CSS tokens and HTML snippets.

**Brand feel:** clean, trustworthy, campus-navy — *not* a generic SaaS blue.
Warm accent colors were removed on purpose: the palette stays cool and
navy-led everywhere. The warmth comes from the serif headings and the copy
voice, never from orange/yellow/red accents.

---

## 1. Color

| Token | Value | Use |
|---|---|---|
| `--bg` | `#EEF2F8` | Page background (soft blue-white) |
| `--surface` | `#FFFFFF` | Cards, panels, inputs |
| `--navy` | `#14213D` | Primary accent: buttons, heading badges, active icons, CTA band |
| `--navy-deep` | `#0A1B33` | Hover / pressed state of primary buttons |
| `--navy-mid` | `#1B2A4A` | Secondary icon strokes, band accents |
| `--blue-2` | `#2C4770` | Secondary avatar color |
| `--blue-3` | `#5C7EA6` | Tertiary avatar color |
| `--band` | `#DCE6F5` | Full-width "value prop" strip background |
| `--ink` | `#1B2A41` | Body copy, footer background |
| `--muted-strong` | `rgba(27,42,65,0.72)` | Secondary text (descriptions, subtitles) |
| `--muted` | `rgba(27,42,65,0.55)` | Tertiary text (meta, captions, placeholders) |
| `--line` | `rgba(27,42,65,0.08)` | Default hairline / card border |
| `--line-soft` | `rgba(27,42,65,0.06)` | Subtle dividers |
| `--line-strong` | `rgba(27,42,65,0.12)` | Input borders, emphasized dividers |
| `--tint` | `rgba(20,33,61,0.10)` | Badge / icon-box background |
| `--danger` | `#8A3B42` | Status only: error text, destructive (Delete) buttons |
| `--danger-soft` | `#F6EBEC` | Status only: error banner background, Delete hover |

Status banners (survey result, etc.): success = navy background + white
text; waiting / not-ideal = `--band` background; error = `--danger-soft`
background + `--danger` text. Toasts are navy pills with white text.

**Rules**
- Navy is the only accent. Don't introduce warm colors (orange, amber, coral, red-pink) for decoration.
- Avatars rotate through `--navy` → `--blue-2` → `--blue-3`.
- Text on navy or `--ink` backgrounds is white (muted: `rgba(255,255,255,0.72)`).
- Error/success states, if needed, should be muted and used only for status text — never as brand accents.

## 2. Typography

Load both from Google Fonts:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Nunito:wght@400;600;700&display=swap" rel="stylesheet">
```

| Role | Font | Weight | Notes |
|---|---|---|---|
| Display / H1–H3 | **Fraunces** (serif) | 600–700 | Character and warmth against the cool palette |
| Avatar initials | Fraunces | 700 | |
| Body, UI, buttons, labels, inputs | **Nunito** (sans) | 400 / 600 / 700 | Everything that isn't a heading |

Suggested scale (desktop → mobile):

| Element | Size | Line height |
|---|---|---|
| Hero H1 | 56px → 36px | 1.1 |
| Section H2 | 40px → 28px | 1.15 |
| Card title H3 | 20px | 1.3 |
| Body | 16px | 1.6 |
| Small / meta | 14px | 1.5 |
| Badge | 13px, weight 700 | 1 |

## 3. Shape, elevation & spacing

| Thing | Spec |
|---|---|
| Buttons | Pill: `border-radius: 999px` |
| Cards | `border-radius: 20px` (small) – `28px` (large/hero) |
| Card shadow | `0 8px 24px rgba(27,42,65,0.08)`; hover up to `0 12px 24px rgba(27,42,65,0.14)`; resting minimum `0 8px 16px rgba(27,42,65,0.05)` |
| Icon container | 56×56px, `border-radius: 16px`, `--tint` background |
| Icons | Navy stroke, `stroke-width: 1.8`, round caps & joins, no fills (except small connector accents) |
| Badges / chips | Small pill, navy text on `--tint` |
| Section padding | 80–96px vertical, 80px horizontal on desktop; 56px / 20px on mobile |
| Grid gaps | 24px (cards), 32px (feature grid) |

## 4. Drop-in CSS tokens

Paste this at the top of every page's `<style>` (or into a shared `ui/studymatch.css`):

```css
:root {
  --bg: #EEF2F8;
  --surface: #FFFFFF;
  --navy: #14213D;
  --navy-deep: #0A1B33;
  --navy-mid: #1B2A4A;
  --blue-2: #2C4770;
  --blue-3: #5C7EA6;
  --band: #DCE6F5;
  --ink: #1B2A41;
  --muted-strong: rgba(27,42,65,0.72);
  --muted: rgba(27,42,65,0.55);
  --line-soft: rgba(27,42,65,0.06);
  --line: rgba(27,42,65,0.08);
  --line-strong: rgba(27,42,65,0.12);
  --tint: rgba(20,33,61,0.10);
  --danger: #8A3B42;
  --danger-soft: #F6EBEC;

  --font-display: "Fraunces", Georgia, "Times New Roman", serif;
  --font-body: "Nunito", system-ui, -apple-system, "Segoe UI", sans-serif;

  --radius-pill: 999px;
  --radius-card: 24px;
  --radius-card-lg: 28px;
  --radius-icon: 16px;
  --shadow-card: 0 8px 24px rgba(27,42,65,0.08);
  --shadow-card-hover: 0 12px 24px rgba(27,42,65,0.14);
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-body);
  font-size: 16px;
  line-height: 1.6;
}

h1, h2, h3 {
  font-family: var(--font-display);
  font-weight: 700;
  color: var(--navy);
  margin: 0 0 .5em;
}
h3 { font-weight: 600; }

.section { padding: 88px 80px; }
@media (max-width: 720px) { .section { padding: 56px 20px; } }
```

## 5. Components

### Buttons

```css
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  padding: 12px 26px;
  border-radius: var(--radius-pill);
  font: 700 15px/1 var(--font-body);
  cursor: pointer;
  transition: background .15s, color .15s, transform .1s;
}
.btn-primary { background: var(--navy); color: #fff; border: 2px solid var(--navy); }
.btn-primary:hover  { background: var(--navy-deep); border-color: var(--navy-deep); }
.btn-primary:active { background: var(--navy-deep); transform: translateY(1px); }

.btn-ghost { background: transparent; color: var(--navy); border: 2px solid var(--navy); }
.btn-ghost:hover { background: var(--tint); }

/* On the navy CTA band */
.btn-on-navy { background: #fff; color: var(--navy); border: 2px solid #fff; }
.btn-on-navy:hover { background: var(--band); border-color: var(--band); }

.btn:focus-visible { outline: 3px solid var(--blue-3); outline-offset: 3px; }
```

```html
<button class="btn btn-primary">Find my study group</button>
<button class="btn btn-ghost">How it works</button>
```

### Badge / pill label

```css
.badge {
  display: inline-block; padding: 6px 12px;
  border-radius: var(--radius-pill);
  background: var(--tint); color: var(--navy);
  font: 700 13px/1 var(--font-body); letter-spacing: .02em;
}
```

```html
<span class="badge">CMPSC 121</span>
```

Tag chips on profile cards use the same `.badge` style.

### Card

```css
.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: 28px;
}
.card.is-interactive { transition: box-shadow .2s, transform .2s; }
.card.is-interactive:hover { box-shadow: var(--shadow-card-hover); transform: translateY(-2px); }
```

### Icon box

```css
.icon-box {
  width: 56px; height: 56px; flex: none;
  display: grid; place-items: center;
  border-radius: var(--radius-icon);
  background: var(--tint);
  color: var(--navy);
}
.icon-box svg {
  width: 28px; height: 28px;
  fill: none; stroke: currentColor; stroke-width: 1.8;
  stroke-linecap: round; stroke-linejoin: round;
}
```

```html
<div class="icon-box">
  <svg viewBox="0 0 24 24"><path d="M4 19.5V5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M8 7h7M8 11h5"/></svg>
</div>
```

### Avatar

Solid circle, single white initial in Fraunces. Rotate background colors.

```css
.avatar {
  width: 56px; height: 56px; border-radius: 50%;
  display: grid; place-items: center; flex: none;
  color: #fff; font: 700 22px/1 var(--font-display);
  background: var(--navy);
}
.avatar.c2 { background: var(--blue-2); }
.avatar.c3 { background: var(--blue-3); }
.avatar.lg { width: 80px; height: 80px; font-size: 32px; }
```

```html
<div class="avatar">J</div>
<div class="avatar c2">M</div>
<div class="avatar c3">A</div>
```

### "Matched" pair

Two avatars joined by a small white circle holding an outline heart — the
visual shorthand for a successful match.

```css
.match { display: inline-flex; align-items: center; }
.match .avatar { width: 72px; height: 72px; font-size: 28px; border: 4px solid var(--surface); }
.match-link {
  width: 40px; height: 40px; margin: 0 -12px; z-index: 1;
  border-radius: 50%; background: var(--surface);
  display: grid; place-items: center;
  box-shadow: 0 4px 12px rgba(27,42,65,0.12);
}
.match-link svg {
  width: 20px; height: 20px; fill: none;
  stroke: var(--navy); stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round;
}
```

```html
<div class="match">
  <div class="avatar">J</div>
  <div class="match-link">
    <svg viewBox="0 0 24 24"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21.2l8.8-8.8a5.5 5.5 0 0 0 0-7.8z"/></svg>
  </div>
  <div class="avatar c2">M</div>
</div>
```

### Step indicator

Numbered (or icon) circles connected by a dashed line.

```css
.steps { display: flex; justify-content: space-between; position: relative; }
.steps::before {
  content: ""; position: absolute; top: 28px; left: 12%; right: 12%;
  border-top: 2px dashed rgba(27,42,65,0.15);
}
.step { position: relative; flex: 1; text-align: center; padding: 0 12px; }
.step-dot {
  width: 56px; height: 56px; margin: 0 auto 16px; border-radius: 50%;
  display: grid; place-items: center;
  background: var(--navy); color: #fff;
  font: 700 20px/1 var(--font-display);
  box-shadow: 0 0 0 8px var(--bg); /* masks the dashed line behind the dot */
}
.step p { color: var(--muted-strong); font-size: 15px; margin: 0; }
@media (max-width: 720px) {
  .steps { flex-direction: column; gap: 32px; }
  .steps::before { display: none; }
}
```

```html
<div class="steps">
  <div class="step"><div class="step-dot">1</div><h3>Take the quiz</h3><p>Five minutes on how you like to study.</p></div>
  <div class="step"><div class="step-dot">2</div><h3>Get matched</h3><p>We group you with classmates who fit.</p></div>
  <div class="step"><div class="step-dot">3</div><h3>Meet up</h3><p>Grab a table at Pattee and get to work.</p></div>
</div>
```

### Feature grid (4 columns)

Icon box + bold title + muted description.

```css
.feature-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 32px; }
@media (max-width: 1024px) { .feature-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 560px)  { .feature-grid { grid-template-columns: 1fr; } }
.feature h3 { font-size: 20px; margin: 20px 0 8px; }
.feature p  { color: var(--muted-strong); margin: 0; }
```

```html
<div class="feature-grid">
  <div class="feature card">
    <div class="icon-box"><!-- svg --></div>
    <h3>Same-course matches</h3>
    <p>Only people actually in your section of STAT 200.</p>
  </div>
  <!-- ×4 -->
</div>
```

### Profile preview card (3 columns)

Avatar + name / major · year + 2 tag chips + one-line blurb.

```css
.profile-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; }
@media (max-width: 960px) { .profile-grid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 600px) { .profile-grid { grid-template-columns: 1fr; } }
.profile-head { display: flex; gap: 14px; align-items: center; }
.profile-name { font: 700 17px/1.3 var(--font-body); color: var(--ink); margin: 0; }
.profile-meta { font-size: 14px; color: var(--muted); margin: 0; }
.profile-tags { display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0 12px; }
.profile-blurb { color: var(--muted-strong); font-size: 15px; margin: 0; }
```

```html
<div class="card profile">
  <div class="profile-head">
    <div class="avatar c2">M</div>
    <div>
      <p class="profile-name">Maya Chen</p>
      <p class="profile-meta">Data Sciences · Junior</p>
    </div>
  </div>
  <div class="profile-tags"><span class="badge">DS 220</span><span class="badge">Night owl</span></div>
  <p class="profile-blurb">Down for late sessions at the HUB before exams.</p>
</div>
```

### Value-prop band

Full-width light blue strip.

```css
.band { background: var(--band); padding: 64px 80px; }
.band h2 { color: var(--navy); }
.band .icon-box { background: var(--surface); color: var(--navy-mid); }
```

### CTA band

Full-width navy strip with white text and a white pill button.

```css
.cta-band { background: var(--navy); color: #fff; padding: 88px 80px; text-align: center; }
.cta-band h2 { color: #fff; }
.cta-band p  { color: rgba(255,255,255,0.72); max-width: 560px; margin: 0 auto 28px; }
```

```html
<section class="cta-band">
  <h2>Stop studying for CMPSC 121 alone.</h2>
  <p>Take the quiz once and we'll find your people.</p>
  <a class="btn btn-on-navy" href="/login">Get matched</a>
</section>
```

### Form inputs (login, survey, profile setup)

Not in the original brief — derived from the same tokens so forms match.

```css
.field label { display: block; font: 700 14px/1.4 var(--font-body); color: var(--ink); margin-bottom: 6px; }
.input {
  width: 100%; box-sizing: border-box;
  padding: 12px 16px; border-radius: 14px;
  border: 1.5px solid var(--line-strong); background: var(--surface);
  font: 400 16px/1.4 var(--font-body); color: var(--ink);
}
.input::placeholder { color: var(--muted); }
.input:focus { outline: none; border-color: var(--navy); box-shadow: 0 0 0 4px var(--tint); }
```

Survey scale options (1–5) use pill-shaped toggles: `.btn-ghost` at rest,
`.btn-primary` when selected.

### Chat (derived)

- Own message: `--navy` background, white text, radius `20px 20px 6px 20px`.
- Others' messages: `--surface` background, `--ink` text, `1px solid var(--line)`, radius `20px 20px 20px 6px`, avatar (32px) to the left.
- Timestamps/meta: 12px `--muted`.
- Composer: `.input` with pill radius + circular `.btn-primary` send button.

### Footer

`--ink` background, white text, links at `rgba(255,255,255,0.72)`, hover to white.

## 6. Voice & copy

- Friendly, casual, encouraging — written for US college students at Penn
  State, not corporate SaaS.
- Use real PSU-flavored details where they help: course codes (`CMPSC 121`,
  `STAT 200`, `DS 220`, `MATH 140`), campus spots (Pattee Library, the HUB,
  Paterno, the Creamery), "State College", "finals week".
- Short sentences, second person ("you"), contractions welcome.
  ✅ "Find people who actually want to study at 9pm."
  ❌ "Leverage our AI-driven collaborative learning platform."
- **Never** use Penn State's official logo, wordmark, seal, or Nittany Lion
  marks. StudyMatch is independent — its own name, its own look.

## 7. Checklist for any new screen

- [ ] Page bg `--bg`, content on white cards with 20–28px radius + soft shadow
- [ ] Headings in Fraunces, everything else in Nunito
- [ ] Every button is a pill; one primary (navy) action per view
- [ ] Icons are navy stroke-only in a 56px tinted box
- [ ] No warm accent colors anywhere
- [ ] Generous spacing (80–96px section padding on desktop)
- [ ] Copy sounds like a friendly upperclassman, not a SaaS landing page
- [ ] Works at ~400px wide (grids collapse, section padding shrinks)
