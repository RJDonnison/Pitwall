---
name: Grand Prix Broadsheet Strategy System
colors:
  surface: '#f9f9f8'
  surface-dim: '#dadad9'
  surface-bright: '#f9f9f8'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f4f3'
  surface-container: '#eeeeed'
  surface-container-high: '#e8e8e7'
  surface-container-highest: '#e2e2e2'
  on-surface: '#1a1c1c'
  on-surface-variant: '#59413e'
  inverse-surface: '#2f3130'
  inverse-on-surface: '#f1f1f0'
  outline: '#8d706d'
  outline-variant: '#e1bfbb'
  surface-tint: '#b02d29'
  primary: '#760009'
  on-primary: '#ffffff'
  primary-container: '#991b1b'
  on-primary-container: '#ffaaa1'
  inverse-primary: '#ffb4ac'
  secondary: '#625d5b'
  on-secondary: '#ffffff'
  secondary-container: '#e9e1dd'
  on-secondary-container: '#686361'
  tertiary: '#3c3632'
  on-tertiary: '#ffffff'
  tertiary-container: '#534d49'
  on-tertiary-container: '#c7beb8'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#ffdad6'
  primary-fixed-dim: '#ffb4ac'
  on-primary-fixed: '#410002'
  on-primary-fixed-variant: '#8e1214'
  secondary-fixed: '#e9e1dd'
  secondary-fixed-dim: '#ccc5c2'
  on-secondary-fixed: '#1e1b19'
  on-secondary-fixed-variant: '#4a4643'
  tertiary-fixed: '#eae1da'
  tertiary-fixed-dim: '#cec5bf'
  on-tertiary-fixed: '#1f1b17'
  on-tertiary-fixed-variant: '#4b4641'
  background: '#f9f9f8'
  on-background: '#1a1c1c'
  surface-variant: '#e2e2e2'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 3.5rem
    fontWeight: '400'
    lineHeight: 3.75rem
    letterSpacing: -0.02em
  headline-xl-mobile:
    fontFamily: Inter
    fontSize: 2.25rem
    fontWeight: '400'
    lineHeight: 2.5rem
    letterSpacing: -0.015em
  headline-lg:
    fontFamily: Inter
    fontSize: 2.5rem
    fontWeight: '400'
    lineHeight: 2.75rem
    letterSpacing: -0.015em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 1.75rem
    fontWeight: '400'
    lineHeight: 2rem
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Inter
    fontSize: 1.75rem
    fontWeight: '500'
    lineHeight: 2.125rem
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Inter
    fontSize: 1.25rem
    fontWeight: '500'
    lineHeight: 1.625rem
    letterSpacing: 0em
  body-lg:
    fontFamily: Inter
    fontSize: 1.125rem
    fontWeight: '400'
    lineHeight: 1.75rem
    letterSpacing: -0.01em
  body-md:
    fontFamily: Inter
    fontSize: 0.9375rem
    fontWeight: '400'
    lineHeight: 1.5rem
    letterSpacing: -0.005em
  body-sm:
    fontFamily: Inter
    fontSize: 0.8125rem
    fontWeight: '400'
    lineHeight: 1.25rem
    letterSpacing: 0em
  label-md:
    fontFamily: Inter
    fontSize: 0.75rem
    fontWeight: '600'
    lineHeight: 1rem
    letterSpacing: 0.06em
  label-sm:
    fontFamily: Inter
    fontSize: 0.6875rem
    fontWeight: '500'
    lineHeight: 0.875rem
    letterSpacing: 0.08em
  data-mono:
    fontFamily: Inter
    fontSize: 0.875rem
    fontWeight: '500'
    lineHeight: 1.25rem
    letterSpacing: 0.02em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1.5rem
  gutter-mobile: 0.75rem
  margin: 3rem
  margin-mobile: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

This design system combines the authoritative presence of classic motorsport broadsheet journalism with the surgical precision of modern technical interfaces. Built as an analytical strategy workbench, it targets F1 strategists, data-driven fantasy managers, and telemetry purists who demand dense information architecture without visual noise.

The aesthetic philosophy rejects modern SaaS tropes: no diffused neon glows, no synthetic glassmorphism, no overly rounded bubble containers, and no artificial gradients. Instead, the interface draws heritage from printed racing yearbooks, technical paddock clipboards, and high-end editorial interactives. High-contrast typography pairs clean, highly legible sans-serif typefaces for both narrative weight and razor-sharp figures for telemetry, lap times, and budget constraints. The tone is restrained, analytical, physical, and composed.

## Colors

The palette establishes an authentic paper-ground workspace punctuated by precise vermilion accents.

- **Primary (`#991B1B`)**: Deep racing vermilion. Reserved strictly for active states, critical status indicators, primary actions, and strategic deltas. It is never used in broad washes or decorative fills.
- **Secondary (`#1C1917`)**: Warm pitch black. Used for high-contrast headlines, primary metrics, structural rules, and primary text to evoke heavy printer ink on raw paper.
- **Tertiary (`#78716C`)**: Warm graphite stone. Used for metadata labels, auxiliary telemetry, table header indices, and deactivated states.
- **Neutral Canvas (`#FBFBFA`)**: Archival newsprint ground. A warm, matte off-white providing tactile substrate warmth.
- **Surface Elevation (`#F4F4F1`)**: Secondary substrate for data columns, contrasting modules, and inset data wells.
- **Hairline Rule (`#E5E5E3`)**: 1px structural boundary line dividing cells and editorial columns without casting visual weight.
- **Status Deliberation**: Positive deltas rely on a subdued racing forest (`#166534`), cautions on warm ochre (`#B45309`), and critical drop zones on the primary vermilion (`#991B1B`). All status accents are anchored by neutral background pills or hairline borders, entirely eschewing saturated neon badge patterns.

## Typography

Typography acts as the fundamental architecture of this system. Built entirely on **Inter**, the typography mirrors the clean, highly legible precision of modern technical interfaces and data dashboards.

- **Inter (Headlines & Editorial)**: Deployed across article titles, section leads, team summaries, and narrative driver notes. Provides a crisp, modern editorial aesthetic.
- **Inter (Body & Technical Engine)**: Serves as the technical engine for the workbench. Used across driver rosters, timing trees, financial budget caps, race delta tables, and micro-labels. Figures must consistently enforce tabular alignments (`font-variant-numeric: tabular-nums`) so numbers stack cleanly in dense vertical columns.
- **Labels & Microcopy**: Rendered in uppercase Inter with relaxed tracking (`0.06em` to `0.08em`), evoking paddock technical manifests and telemetry printouts.

## Layout & Spacing

The layout is grounded in a disciplined broadsheet grid system. The canvas establishes clarity through unyielding alignment, explicit modular rows, and sharp 1px structural dividing lines instead of floatation.

- **Grid Engine**: 12-column desktop grid with a max width of 1440px, transitioning to an 8-column layout on tablet, and a strict 4-column column on mobile.
- **Structural Framing**: Columns and rows meet at right angles, demarcated by solid hairline borders (`#E5E5E3`). Rather than nesting boxes inside boxes, elements abut one another in an editorial table matrix.
- **Rhythm**: Spacing follows strict multiples of 4px. Component interiors prioritize horizontal breathing room and dense vertical rhythm, ensuring high data density without crowding.
- **Editorial Rail**: Layouts frequently feature an asymmetrical 8:4 split—eight columns dedicated to the visual strategy board, transfer market, and circuit telemetry, with four columns reserved for the live financial balance sheet, chip activation status, and editorial tactical notes.

## Elevation & Depth

This system operates entirely without drop shadows, elevation blurs, or faux-3D layering. Depth is communicated strictly through surface tone transitions and structural linework.

- **Flat Substrates**: All panels reside on the physical plane. Hierarchy is defined by shifting from Canvas (`#FBFBFA`) to Workspace Inset (`#F4F4F1`) or Ink Solid (`#1C1917`).
- **Hairline Boundaries**: Modals, slide-out data drawers, and pinned headers rely on a 1px solid rule (`#E5E5E3`) to establish edges.
- **Z-Index Layering**: Floating action trays or sticky roster sidebars dock cleanly to screen edges with crisp 1px borders rather than diffuse floating shadows.
- **State Changes**: Interactive elevation is represented by color inversion or border transformation (e.g., `#E5E5E3` shifting to `#1C1917` or `#991B1B`), reinforcing a tangible, mechanical response.

## Shapes

The shape system utilizes a subtly rounded geometry (`roundedness: 2`), applying a restrained corner radius (0.5rem default) to soften the mechanical broadsheet density.

Every element—including buttons, input fields, badges, strategy cards, tab bars, modals, and driver portrait frames—features clean, subtle rounded corners. This geometry retains the physical, ink-on-paper broadsheet character and evokes the exactitude of racing telemetry monitors, timing sheets, and technical rulebooks while introducing a refined tactile feel.

## Components

### Buttons
- **Primary**: Solid pitch black (`#1C1917`) background, neutral paper text (`#FBFBFA`), soft rounded corners (`0.5rem`), 1px matching border. Hover shifts background to racing vermilion (`#991B1B`).
- **Secondary / Outline**: Neutral paper background, 1px `#1C1917` or `#E5E5E3` border, pitch black text. Hover shifts to `#F4F4F1` surface with pitch black border.
- **Critical / Flag**: Vermilion (`#991B1B`) outline, matching text, transparent ground. Hover inverts to solid vermilion fill with white text.
- **Sizing**: Compact height (36px desktop, 40px mobile), Inter label typography in uppercase with `0.06em` letter spacing.

### Tabs & Navigation
- **Editorial Rail Tabs**: Sharp bottom-bordered navigation. Resting state uses `#78716C` text with no bottom line. Active state features pitch black text and a distinct 2px solid `#991B1B` bottom rule.
- **Sub-segment Controls**: Inset boxed horizontal tab strip against `#F4F4F1`. Individual tabs are separated by 1px rules; the active tab takes a `#FBFBFA` background with pitch black text.

### Cards & Modules
- Border-defined cells with 1px `#E5E5E3` perimeters, soft rounded corners, and `#FBFBFA` background.
- Headers are divided from body content with a continuous 1px horizontal rule. Top metadata is rendered in small Inter uppercase labels.

### Data Tables & Roster Lists
- **Rows**: Fixed-height, alternating `#FBFBFA` and `#F4F4F1` striping or separated by crisp 1px horizontal lines.
- **Alignment**: Driver names and team monikers align left (Inter Body); prices, point deltas, and telemetry align right using Inter Data Mono with tabular numbers.
- **Hover**: Subtle row highlight shifts to `#EAEAE7` with instant transitions.

### Chips & Status Indicators
- Rectangular blocks with soft rounded corners. No hard 0px boxes or extreme pill shapes.
- 1px border with a soft neutral fill (`#F4F4F1`). A small 6px square indicator (green `#166534`, yellow `#B45309`, or red `#991B1B`) precedes the micro-label.

### Form Inputs & Selectors
- Flat fields with a 1px `#E5E5E3` border, soft rounded corners, and paper white background. Focus state transitions the border directly to `#1C1917` with no glow ring. Labels sit squarely above the field in uppercase Inter label style.

### Strategy Workbench Additions
- **Budget Meter**: A horizontal segmented line rule. Used funds are displayed in solid `#1C1917`, pending transfers in `#991B1B`, and free budget in faint `#E5E5E3`.
- **Driver Position Badge**: A gently rounded 24x24px black box housing a white monospaced finishing position or grid ranking.
