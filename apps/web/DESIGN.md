# Design System

## Product Surface

The product is a desktop scheduling workbench. The release acceptance viewports
are 1280x800, 1440x900, and 1920x1080. Layout prioritizes a persistent
navigation rail, a compact utility header, and wide content bands for tables,
timelines, diffs, and operational detail.

## Visual Direction

Use a restrained, bright industrial palette. Graphite neutrals create stable
structure; cobalt blue is reserved for primary actions, active navigation, and
selected objects. Success, warning, danger, and information each have a
separate semantic hue. Do not offer dark mode in the first release.

```css
:root {
  --surface-canvas: oklch(0.97 0.006 250);
  --surface-raised: oklch(1 0 0);
  --surface-subtle: oklch(0.94 0.012 250);
  --border-subtle: oklch(0.84 0.018 250);
  --ink-strong: oklch(0.24 0.02 250);
  --ink-muted: oklch(0.46 0.025 250);
  --action-primary: oklch(0.48 0.17 255);
  --status-success: oklch(0.54 0.13 150);
  --status-warning: oklch(0.68 0.15 75);
  --status-danger: oklch(0.55 0.19 28);
  --status-info: oklch(0.54 0.13 245);
}
```

## Typography

Use one UI sans-serif stack: `"IBM Plex Sans", "Noto Sans SC", sans-serif`.
Page titles are 24px/30px, section headings 18px/24px, body 14px/20px, compact
labels and table content 13px/18px. Use tabular numerals for IDs, counts,
durations, and timestamps. Product type is fixed-scale, never viewport-scaled.

## Components

Use square-to-soft controls: buttons and inputs use 6px radius; cards and
dialogs use at most 8px. Tables have fixed row rhythm and sticky headers when
scrolling. Icon buttons use Lucide icons and accessible labels. Primary actions
are cobalt; secondary actions are neutral; destructive actions require danger
semantics and confirmation. Skeletons replace content during initial loading.

Every interactive component defines default, hover, focus-visible, active,
disabled, loading, error, and permission-denied behavior. Use 150-200ms
opacity/color/transform transitions only for state change. Reduced-motion mode
removes transforms and uses immediate changes.

## Layout

The app shell uses a 232px navigation rail, 56px utility header, and a content
area with 24px desktop gutters. Page sections are unframed content bands;
cards are limited to repeated operational items, compact metrics, and dialogs.
Never nest cards. Filters, table actions, and timeline controls remain aligned
to their data surface rather than floating independently.

## Data Visualization

Use Apache ECharts only where it aids a scheduling decision: capacity trend,
SLA risk distribution, and event volume. The Gantt view is an interactive
operational surface, not a decorative chart. Frozen steps, changed steps,
blocked work, and baseline schedule positions have distinct non-color cues.

## Accessibility

Maintain 4.5:1 contrast for body text and controls, keyboard order matching
visual order, visible focus, button names, form labels, table headers, live
status for asynchronous work, and text/icon state labels. Do not use color as
the sole signal for SLA, approval, or service degradation.
