# Accessibility scan (axe-core)

Generated 2026-10-11 14:36 from 36 scans (every page, per role, at 375, 768 and 1280 px in Chromium and 1280 px in WebKit) with WCAG 2.0 and 2.1 A and AA rules plus axe best practices. Nothing is fixed yet; this is the starting list for the accessibility stage.

## Violations by severity

Unique violations: one per rule per page, counted once however many widths or roles show it.

| Severity | Unique violations |
| --- | --- |
| critical | 1 |
| serious | 1 |
| moderate | 0 |
| minor | 2 |
| **Total** | **4** |

Per run (the same rule on the same page counts once per run):

| Run | critical | serious | moderate | minor | Total |
| --- | --- | --- | --- | --- | --- |
| chromium-1280 | 1 | 1 | 0 | 2 | 4 |
| chromium-375 | 1 | 1 | 0 | 1 | 3 |
| chromium-768 | 1 | 1 | 0 | 2 | 4 |
| webkit-1280 | 1 | 1 | 0 | 2 | 4 |

## Every unique violation

| Severity | Rule | Page | What is wrong | Elements | Runs | Example |
| --- | --- | --- | --- | --- | --- | --- |
| critical | `aria-required-children` | /coordinator/donations/[id] | Certain ARIA roles must contain particular children | 3 | 4 | `<div role="row" class="grid grid-cols-2 gap-2 rounded-lg border bg-white p-3 md:grid-cols-` |
| serious | `definition-list` | /admin/dashboard | <dl> elements must only directly contain properly-ordered <dt> and <dd> groups, <script>, <template> or <div> elements | 1 | 4 | `<dl class="grid grid-cols-2 gap-3 lg:grid-cols-4">` |
| minor | `empty-table-header` | /coordinator/donations | Table header text should not be empty | 1 | 3 | `<th class="px-4 py-2"></th>` |
| minor | `empty-table-header` | /coordinator/forecasts | Table header text should not be empty | 1 | 4 | `<th class="py-2 pr-4 font-medium"></th>` |
