# Release Notes Format

This document defines the standard format for StarPost release notes. Every
release's notes must follow this structure so they read consistently and can be
processed automatically (e.g. by the Slack release workflow).

## Rules

- **Start with a summary.** The first thing in the notes is **1–2 sentences**
  describing the changes in the release. No header above it.
- **Group every item under a category header.** Each release-note item is a
  bullet point that lives under exactly **one** of the category headers below.
- **Only use these category headers**, written exactly as shown:
  - **New Features**
  - **Changes**
  - **Fixes**
  - **Removed**
  - **Security**
- **Order the headers** as follows (skip any that don't apply):
  1. New Features
  2. Changes
  3. Fixes
  4. Removed
  5. Security
- **Omit empty headers.** If a release has no items for a category, do not
  include that header at all for that version.
- **Bold the headers — and only the headers.** Write each category header in
  bold (e.g. `**New Features**`). Bold is used for nothing else: the summary and
  every item are plain text.
- **Format every bullet as ` - `.** Each item begins with a space, a single
  dash, and a space (` - `), then the item text.

## What goes under each header

- **New Features** — new functionality added in this release.
- **Changes** — changes to existing behaviour (modifications, not new features
  or bug fixes).
- **Fixes** — bug fixes.
- **Removed** — functionality that has been removed.
- **Security** — security-related changes (hardening, vulnerability fixes,
  credential handling).

## Template

```markdown
<1–2 sentences summarising the release.>

**New Features**
 - <item>
 - <item>

**Changes**
 - <item>

**Fixes**
 - <item>

**Removed**
 - <item>

**Security**
 - <item>
```

## Example

```markdown
This release adds plot-customization controls and an optional data-smoothing
toggle, and speeds up application startup.

**New Features**
 - Per-monitor line colours, selectable from a swatch beside each monitor.
 - A "Smooth data" toggle that applies a configurable moving average.

**Changes**
 - Comparison plots now give every line its own colour.

**Fixes**
 - A scaled legend now tracks the cursor 1:1 when dragged.
```

In the example above, the **Removed** and **Security** headers are omitted
because the release had no items for them.
