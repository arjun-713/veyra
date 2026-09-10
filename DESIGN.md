---
name: Veyra Scope
description: Bench-instrument visualizer for real LiDAR dataset frames.
colors:
  panel: "#141414"
  panel-raised: "#1c1c1a"
  panel-inset: "#232320"
  void: "#0b0b0b"
  bone: "#ede8dc"
  signal-red: "#ff3b30"
  sweep-amber: "#ffb000"
  pair-green: "#3ddc84"
  steel-line: "rgba(138,143,152,0.35)"
  steel-solid: "#3a3d42"
typography:
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "20px"
    fontWeight: 800
    letterSpacing: "0.06em"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "14px"
    lineHeight: 1.45
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    letterSpacing: "0.14em"
  readout:
    fontFamily: "ui-monospace, SF Mono, Cascadia Mono, Menlo, Consolas, monospace"
    fontSize: "30px"
    letterSpacing: "0.08em"
rounded:
  none: "0px"
spacing:
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "18px"
components:
  instrument-button:
    backgroundColor: "{colors.panel-raised}"
    textColor: "{colors.bone}"
    rounded: "{rounded.none}"
    padding: "9px 14px"
  instrument-button-active:
    backgroundColor: "{colors.signal-red}"
    textColor: "{colors.panel}"
    rounded: "{rounded.none}"
    padding: "9px 14px"
  readout-frame:
    backgroundColor: "{colors.panel-raised}"
    textColor: "{colors.signal-red}"
    rounded: "{rounded.none}"
    padding: "2px 0 10px"
  step-key:
    backgroundColor: "{colors.panel-inset}"
    textColor: "{colors.bone}"
    rounded: "{rounded.none}"
    height: "44px"
  tempo-field:
    backgroundColor: "{colors.void}"
    textColor: "{colors.sweep-amber}"
    rounded: "{rounded.none}"
    padding: "7px 8px"
---

# Design System: Veyra Scope

## Overview

**Creative North Star: "The Calibration Bench"**

Veyra Scope looks like the rack instrument it behaves as: charcoal powder-coat panels separated by deep gaps, bone silkscreen caps labeling every control, LED-red reserved for the live value, amber for the sweep in motion. Nothing decorates; everything reports. Density is high but grouped — viewport, readouts, and transport sit as three cut blocks, each internally tight, each separated generously. The system refuses the generic dashboard card grid: panels never nest, hierarchy comes from position and light, not chrome.

**Key Characteristics:**
- Instrument blocks with steel hairline borders, square corners, zero shadows.
- One red, one amber, one green — each with a single job (live, motion, paired).
- Tabular mono numerals everywhere a number can change.

## Colors

Restrained charcoal world with a three-lamp signal vocabulary: red is the live value, amber is motion, green is pairing confirmed.

### Primary
- **Signal Red** (#ff3b30): the live value only — active frame id, armed RUN, selected toggles, current step.

### Secondary
- **Sweep Amber** (#ffb000): motion and position in sequence — playhead step, tempo field, focus rings, active bank wash.

### Tertiary
- **Pair Green** (#3ddc84): scan-plus-label pairing confirmed; dataset-active lamp for SemanticPOSS.

### Neutral
- **Powder-Coat** (#141414): page ground.
- **Raised Panel** (#1c1c1a): instrument blocks, one step warmer than ground.
- **Inset Well** (#232320): key beds and message wells.
- **Void** (#0b0b0b): viewport and field beds — the darkest surface, behind data.
- **Bone** (#ede8dc): silkscreen text and idle-active fills.
- **Steel Line** (rgba(138,143,152,0.35)): hairline borders and grid.

### Named Rules
**The Three Lamps Rule.** Red, amber, and green each own exactly one meaning (live, motion, paired). No fourth accent, no lamp used as decoration.
**The Void Rule.** Data always sits on the darkest surface (#0b0b0b); chrome never competes with the cloud.

## Typography

**Display Font:** system sans, ExtraBold (-apple-system, Segoe UI, Roboto, Helvetica, Arial)
**Body Font:** system sans, Regular
**Label/Mono Font:** ui-monospace stack for every numeral that can change

**Character:** Workhorse sans for structure, mono for measurement. No display face; the instrument voice is weight, tracking, and tabular figures.

### Hierarchy
- **Display** (800, 20px, 0.06em tracking): product wordmark only.
- **Title** (700, 12px, 0.14em tracking, uppercase): panel headings.
- **Body** (400, 14px, 1.45 line height): messages and help text.
- **Label** (600, 11px, 0.12–0.18em tracking, uppercase): control captions and table heads.
- **Readout** (mono, 30px, 0.08em tracking, Signal Red with soft glow): the live frame id.

### Named Rules
**The Tabular Figures Rule.** Every changing number sets `font-variant-numeric: tabular-nums` so scrubbing never jitters the layout.
**The Caps Carry Weight Rule.** Small caps labels use weight and tracking, never size, to rank above body text.

## Layout

Three cut blocks with deep gaps (18px): scope viewport plus readout rail on one row (fluid 1fr against a fixed 300px rail), transport rail full-width beneath. Panels never nest. Tight 8–12px rhythm inside blocks, generous separation between them, more space above a heading than below it. Below 940px the rail stacks under the scope and the page scrolls; the step strip scrolls horizontally rather than wrapping.

## Elevation & Depth

No shadows anywhere. Depth is conveyed by tonal layering alone: ground, raised panel, inset well, void — four steps darker toward the data. The single exception is light emission, not elevation: LED lamps and the live readout carry a soft red/amber glow, which is the instrument's own behavior.

### Named Rules
**The Flat Panel Rule.** Elevation is declared once, with a 1px steel border. A border under a soft shadow is a ghost panel and never ships.

## Shapes

Square everything (0px radius): panels, keys, fields, buttons. Form comes from hairlines, fills, and the marching-ants selection outline on the active frame step — a 2px dashed amber rule animated along the key's top edge.

## Components

### Buttons
- **Shape:** square corners, 1px steel border, transparent ground.
- **Primary (armed):** Signal Red fill with near-black text (RUN engaged, active toggles).
- **Hover / Focus:** border warms toward bone; keyboard focus takes a 2px amber ring with 2px offset.
- **Secondary:** bone-on-transparent bank keys; the current bank inverts to bone fill with near-black text.

### Step Keys (signature)
- **Shape:** 44px tall keys in a ruled bed; quartile wash tints keys by position in sequence (faint red, orange, yellow, neutral washes).
- **States:** paired frames carry a green pip, unpaired a red pip; the current frame floods amber with black text and wears the marching-ants outline.

### Readouts
- **Frame id:** 30px mono Signal Red with soft glow — the one oversized number on the page.
- **Key-values:** 11px caps labels left, 12px mono values right, one row per fact.

### Histogram Bars
- **Style:** 10px bars in the class's own point-cloud color; length is exactly proportional to the top class. Labels read `name · count` in tabular mono.

### Inputs / Fields
- **Style:** void-black beds, 1px steel stroke, amber mono values (tempo, budget).
- **Focus:** amber ring. **Disabled:** dimmed dither of text, never removed.

### Navigation
- **Dataset switch:** two toggle buttons with lamp dots; the active lamp burns amber (RELLIS-3D) or green (SemanticPOSS), switching the page's identity without repainting it.

## Do's and Don'ts

### Do:
- **Do** keep every number tabular so the layout holds still while scrubbing.
- **Do** use green only for pairing state and red only for the live value.
- **Do** name every error with its recovery (`python3 viewer/server.py` from the repo root).
- **Do** encode bar lengths as exact proportions of the top class.

### Don't:
- **Don't** nest panels or add shadows, gradients, or rounded corners.
- **Don't** show a frame the server did not read from `data/raw/` — no mock clouds, ever.
- **Don't** add a fourth accent or use a lamp color decoratively.
- **Don't** put kickers above headings or gradient fills in text.
