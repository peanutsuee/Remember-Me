<!-- SPDX-License-Identifier: CPAL-1.0 -->

# Dusk Archive Design System

The Remember-Me Dashboard uses an original visual direction called Dusk
Archive. It is quiet, warm, private, and archival without imitating an
enterprise admin console or the Ombre-Brain Dashboard.

## Color tokens

| Token | Value | Use |
| --- | --- | --- |
| `--rm-canvas` | `#F5F1EC` | Main paper canvas |
| `--rm-surface` | `#FFFDF9` | Forms, dialogs, cards |
| `--rm-surface-soft` | `#EEE7F0` | Quiet dusk layer and loading fields |
| `--rm-ink` | `#29242D` | Primary text |
| `--rm-ink-soft` | `#756D79` | Secondary text |
| `--rm-border` | `#D9D0DC` | Rules and field borders |
| `--rm-primary` | `#67506F` | Primary action |
| `--rm-primary-hover` | `#55415D` | Primary hover |
| `--rm-rose` | `#AA6474` | Archive accent |
| `--rm-gold` | `#A87B44` | Warning and locked state |
| `--rm-success` | `#547565` | Success |
| `--rm-danger` | `#A4515F` | Destructive action |
| `--rm-focus` | `#866A91` | Keyboard focus |
| `--rm-shadow` | `rgba(53, 42, 58, 0.12)` | Raised surfaces |

Small derived colors may use `color-mix` for borders and hover states. Blue or
cyan is not the dominant family. The interface avoids full-screen gradients,
neon, pure-black surfaces, bokeh, glassmorphism, and decorative color orbs.

## Typography

The UI uses only local system fonts:

```text
"Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI",
"PingFang SC", "Noto Sans SC", sans-serif
```

Archive headings may use local `Georgia` or `Times New Roman` for a restrained
editorial note. No font is downloaded.

## Spacing and geometry

The spacing scale is 4, 8, 12, 16, 24, 32, 48, and 64 pixels. Cards and dialogs
use an 8-pixel maximum radius; compact controls use 5 pixels. Image areas use a
stable 4:3 aspect ratio. Shadows remain soft and low contrast.

## Focus and status

Keyboard focus uses a visible three-pixel `--rm-focus` outline and offset.
Success uses green plus text, warnings use gold plus text, and danger uses rose
red plus explicit labels. Status is never communicated by color alone.

## Responsive behavior

- Above 960px: full filter row and two-column detail dialog.
- 721–960px: two-column filters and stacked detail content.
- 481–720px: stacked toolbar and compact top actions.
- 320–480px: one-column archive grid and full-width dialog actions.

The grid otherwise uses auto-fill tracks so 768, 1280, and 1440 pixel viewports
gain columns naturally without fixed viewport-scaled type.

## Motion

Transitions use 180 milliseconds. Card lift is limited to two pixels. Skeleton
and spinner motion is functional and subtle. `prefers-reduced-motion: reduce`
reduces animations and transitions to one millisecond.

## Prohibited patterns

Do not add external fonts, external UI libraries, third-party icons, analytics,
large gradients, glass panels, a dark administrator sidebar, unsafe inline
styles or scripts, or user content rendered as HTML.

The Dashboard must remain visually and technically independent from the
Ombre-Brain Dashboard.
