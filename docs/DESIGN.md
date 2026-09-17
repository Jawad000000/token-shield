---
name: Luminous Workspace
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#434655'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#737686'
  outline-variant: '#c3c6d7'
  surface-tint: '#0053db'
  primary: '#004ac6'
  on-primary: '#ffffff'
  primary-container: '#2563eb'
  on-primary-container: '#eeefff'
  inverse-primary: '#b4c5ff'
  secondary: '#006c49'
  on-secondary: '#ffffff'
  secondary-container: '#6cf8bb'
  on-secondary-container: '#00714d'
  tertiary: '#784b00'
  on-tertiary: '#ffffff'
  tertiary-container: '#996100'
  on-tertiary-container: '#ffeedd'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dbe1ff'
  primary-fixed-dim: '#b4c5ff'
  on-primary-fixed: '#00174b'
  on-primary-fixed-variant: '#003ea8'
  secondary-fixed: '#6ffbbe'
  secondary-fixed-dim: '#4edea3'
  on-secondary-fixed: '#002113'
  on-secondary-fixed-variant: '#005236'
  tertiary-fixed: '#ffddb8'
  tertiary-fixed-dim: '#ffb95f'
  on-tertiary-fixed: '#2a1700'
  on-tertiary-fixed-variant: '#653e00'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
typography:
  headline-xl:
    fontFamily: Plus Jakarta Sans
    fontSize: 36px
    fontWeight: '700'
    lineHeight: 44px
    letterSpacing: -0.02em
  headline-xl-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 36px
    letterSpacing: -0.015em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.015em
  headline-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 26px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  label-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
  label-sm:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.02em
  code-md:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 16px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1.5rem
  gutter-mobile: 1rem
  margin: 2rem
  margin-mobile: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

The design system projects clarity, academic focus, and effortless technical competence. Built for students balancing intense coursework with AI-assisted workflows, the interface balances Google-like systematic restraint with the warmth and approachable focus of modern generative workspaces. 

The aesthetic is clean, light, and airy—borrowing structural discipline from modern developer tools and conversational interfaces while introducing soft tactile warmth to alleviate cognitive fatigue. Contrast is maintained strictly for functional hierarchy: text is crisp and readable, status indicators are vibrant yet measured, and UI scaffolding recedes into calm, warm-neutral surfaces. The emotional atmosphere is calm, protective, and empowering.

## Colors

The palette leverages a pristine light foundation supported by cool slate neutrals and purposeful semantic accents:

- **Primary (`#2563EB`)**: A vibrant, dependable blue anchored by its brighter interactive counterpart (`#3B82F6`). Used for primary actions, selected states, navigation highlights, and active prompt indicators.
- **Secondary (`#10B981`)**: A fresh emerald hue dedicated to positive metrics, token savings, preserved contexts, and cost efficiency.
- **Tertiary (`#F59E0B`)**: A warm, luminous amber used for soft rate-limit notices, token consumption warnings, and budget guardrail alerts.
- **Neutrals**: Built on a subtle slate-to-zinc spectrum. Canvas foundations sit at `#F8FAFC` and `#F1F5F9`, elevated surfaces use pure `#FFFFFF`, and structural boundaries rely on low-friction `#E2E8F0` borders. Text hierarchy is anchored by `#0F172A` (primary text), `#475569` (secondary text), and `#94A3B8` (muted cues).

## Typography

Typography establishes an immediate sense of order and high legibility. **Plus Jakarta Sans** brings rounded geometry and approachable authority to page titles, module headers, and section leads. **Inter** powers conversational turns, workspace documents, settings forms, and analytical summaries, guaranteeing high legibility across dense token counters and chat logs. **JetBrains Mono** is introduced for precision telemetry: prompt token weights, context window sizes, pricing formulas, and code snippets.

## Layout & Spacing

The workspace adopts a flexible 12-column grid system bounded by maximum readability containers (`max-w-7xl` for analytical dashboards, `max-w-3xl` for linear chat threads and prompt playgrounds). 

- **Desktop (1024px+)**: 12 columns with `1.5rem` gutters and `2rem` outer page margins. Allows persistent multi-pane productivity layouts (e.g., collapsible sidebar navigation, prompt editor, and live token usage ledger).
- **Tablet (768px - 1023px)**: 8 columns with `1.25rem` gutters and `1.5rem` outer margins. Side panels convert to slide-over drawers or stacked tabbed sections.
- **Mobile (<768px)**: 4 columns with `1rem` gutters and `1rem` edge margins. Workflows collapse into vertical stacks with fixed bottom floating action strips for prompt execution and quick token status.

## Elevation & Depth

Visual hierarchy uses a refined combination of surface tonal tiering and diffused ambient shadows:

1. **Base Layer (Canvas)**: Uses neutral tinted surfaces (`#F8FAFC` to `#F1F5F9`) with no elevation.
2. **Surface Layer (Cards, Modules, Input Panes)**: Pure white (`#FFFFFF`) framed by a hairline border (`1px solid #E2E8F0`). Shadow is subtle and neutral: `0 1px 3px 0 rgba(15, 23, 42, 0.04), 0 1px 2px -1px rgba(15, 23, 42, 0.02)`.
3. **Elevated Overlays (Dropdowns, Command Menus, Popovers)**: Pure white (`#FFFFFF`) with a delicate outer glow and ambient drop shadow: `0 10px 25px -5px rgba(15, 23, 42, 0.08), 0 8px 10px -6px rgba(15, 23, 42, 0.04)`.
4. **Active/Hover States**: Subtly shifts forward with an extra 2px blur expansion and a tinted border accent (`#CBD5E1` or brand-tinted `#BFDBFE`).

## Shapes

The design adopts a generous, contemporary shape language (`roundedness: 2`). Form inputs, interactive chips, and prompt action buttons use `0.75rem` (`12px`) corner radii. Floating panels, chat bubbles, metrics tiles, and content cards feature `1rem` (`16px`) to `1.5rem` (`24px`) roundedness to produce an inviting, comfortable aesthetic. Small indicators, status badges, and icon buttons feature full pill styling (`9999px`) to maintain contrast against rectangular UI blocks.

## Components

### Buttons
- **Primary**: Solid `#2563EB` fill with white text, `10px` vertical by `18px` horizontal padding, `12px` corner radius. Hover transitions to `#1D4ED8`. Active state applies a subtle scale compress (`0.98`).
- **Secondary / Soft**: Subtle `#EFF6FF` background with `#1D4ED8` text and `1px solid transparent`. Hover shifts background to `#DBEAFE`.
- **Outline**: Pure `#FFFFFF` background, `1px solid #E2E8F0`, `#334155` text. On hover, background shifts to `#F8FAFC` with `#0F172A` text.
- **Ghost**: Zero background, `#475569` text. Hover adds `#F1F5F9` background tint.

### Chips & Badges
- Compact pill-shaped elements (`9999px`) with `4px` vertical by `10px` horizontal padding.
- **Token Efficiency (Success)**: Light green surface (`#ECFDF5`), deep emerald text (`#047857`), and a matching border (`#A7F3D0`). Accompanied by a 6px green status dot.
- **Quota Alert (Warning)**: Soft amber surface (`#FFFBEB`), warm amber text (`#B45309`), and border (`#FDE68A`).
- **Model Tag (Neutral)**: `#F1F5F9` surface, `#475569` text, `1px solid #E2E8F0`.

### Cards & Panels
- Constructed from pure `#FFFFFF` resting on `#F8FAFC`.
- Finished with `1px solid #E2E8F0`, a `16px` border radius, and `20px` internal padding.
- Card headers maintain clean separation using a bottom hairline border or generous vertical margin.

### Input Fields & Prompt Composer
- **Standard Field**: Pure `#FFFFFF` fill, `1px solid #CBD5E1`, `12px` border radius. Focus states apply `#2563EB` outline ring with `0 0 0 3px rgba(37, 99, 235, 0.12)`.
- **AI Composer Box**: High-profile container with soft inner padding (`16px`), integrated bottom toolbar for token counts (`JetBrains Mono`), context selection chips, and a prominent floating submit button.

### Lists & Activity Rows
- Borderless table items or separated rows using `1px solid #F1F5F9`.
- Interactive rows transition to `#F8FAFC` with a smooth `150ms` ease-in-out.
- Monospace figures align to tabular numerals (`font-variant-numeric: tabular-nums`).

### Checkboxes & Radio Buttons
- Custom square (`6px` radius) and circular elements sized at `18px`.
- Unchecked: `#FFFFFF` fill with `1px solid #CBD5E1`.
- Checked: Solid `#2563EB` fill with crisp white checkmark or center pip. Focus rings use primary 20% opacity halos.

### Specialized Workspace Modules
- **Token Shield Meter**: A split-segment visual progress bar displaying used vs. cached tokens using `#2563EB` (current run), `#10B981` (cached/saved), and `#F1F5F9` (remaining balance).
- **Context Guard Banner**: A lightweight banner with `12px` radius and a `1px` soft tinted outline warning students before costly context-heavy prompts run.