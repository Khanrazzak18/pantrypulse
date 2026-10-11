# Accessibility

Target: **WCAG 2.1 level AA** for every page, role and screen size. This is what was built, how it is
checked, and what is not covered.

## How it is checked

| Check | Where | What it does |
| --- | --- | --- |
| axe-core gate | `frontend/e2e/a11y.spec.ts` | Scans every page, for every role, in the states people really reach (errors showing, dialogs open, table views open, forms filled in). **Any violation of the `wcag2a`, `wcag2aa`, `wcag21a` or `wcag21aa` rules fails the end-to-end run.** axe's extra best-practice rules are reported as advisory and do not fail it. |
| Behaviour tests | `frontend/e2e/a11y-features.spec.ts` | Checks what axe cannot see: where focus goes, what is announced, what a dialog does, that charts have text alternatives, reduced motion, zoom, and four keyboard-only journeys. |
| Report | `docs/testing/a11y-report.md` | Rewritten by every `make e2e`: pages scanned, WCAG violations by severity (target: none), advisory findings. |
| Checklist | `docs/testing/checklist.md` rows `A11Y-01` to `A11Y-33` | Each feature below is a row with the test that proves it. |

Scans run at 375, 768 and 1280 px in Chromium and at 1280 px in WebKit (Safari's engine).

## What was added

**Getting around**
- **Skip link.** The first Tab on every page (including sign-in) shows "Skip to main content"; Enter moves focus to the main content (`#main-content`). (A11Y-20)
- **Landmarks.** One `banner` (header), one `navigation` named "Main", one `main`, one `contentinfo` (footer), and exactly one `h1` per page. (A11Y-21)
- **A title for every route.** "Donations · PantryPulse", "Impact dashboard · PantryPulse", "Page not found · PantryPulse", and so on, including the error and not-found screens. (A11Y-22)
- **Where you are.** The current navigation link has `aria-current="page"` and is also bold and underlined, so it is not colour alone; a detail page keeps its section marked. The phone menu button says whether it is open (`aria-expanded`). (A11Y-23)
- **Visible focus.** Every control that takes focus gets a 3 px blue outline with a 2 px gap, over any component styling (`globals.css`, `:focus-visible`). (A11Y-24)

**Forms**
- Every field has a visible label (or a screen-reader-only one). In the donation review grid the label also says which row ("Item (row 2)").
- Errors are linked: the field has `aria-invalid="true"` and `aria-describedby` pointing at its message. On a failed submit, focus moves to the first field with a problem (sign-in, donation review, shortage report, allocation edit, monthly summary). Opening the allocation edit form moves focus into it. (A11Y-25)
- The shortage report's two choice groups are `fieldset`s with a legend; a missing choice is linked to the group with `aria-describedby`.

**Announcements**
- Loading, success and error messages are in `role="status"` (polite) or `role="alert"` regions: signing in, approving, editing and rejecting a shipment ("Approved 120 lb of ... for ..."), saving a shortage report, adding a donation to inventory, the chart loading, and the offline banner. When the row you used disappears after an action, focus moves to the message instead of falling back to the top of the page. (A11Y-26)

**Dialogs** (`components/dialog.tsx`, used by "Approve all shown" and "Reject donation")
- Built on the browser's modal `<dialog>`: the rest of the page cannot be reached, and screen readers hear it as a dialog with a name ("alertdialog" for the rejection).
- Tab and Shift+Tab wrap inside; Escape and the cancel button close it; focus returns to the button that opened it. (A11Y-27)
- Two real bugs were found here by the tests and fixed: the browser delivers a dialog's `close` event as a later task, so a quick re-open after Escape was ignored and the late event then closed the new dialog. The dialog now handles Escape itself and ignores a late event from an earlier closing.

**Tables and charts**
- Every table has a caption (visible or screen-reader-only) and header cells with `scope`; row headers use `scope="row"`. The donation items grid is a real ARIA table: column headers and `cell` roles. Scrollable table regions are keyboard-focusable and named. (A11Y-28)
- Every chart (the forecast chart and the five dashboard charts) has: a name, a one-paragraph **text summary** (latest value, lowest and highest, and for the forecast the next week's range) connected with `aria-describedby`, and a **"View as table"** button (`aria-expanded`) that shows the same numbers as a table with a caption. It works from the keyboard. The charts' own built-in keyboard layer is switched off because the table replaces it. (A11Y-29)

**Meaning is not carried by colour alone**
- Statuses are words ("Needs review", "Approved"). Food that expires within 3 days says **"Expiring soon"**; the pantry portal says "(soon)". Chosen options in the shortage form show a ✓ as well as a colour and `aria-pressed`. Chart lines differ in pattern (solid and dashed), not only colour. Fields the AI was unsure about say "AI unsure (60%)" as well as being highlighted. (A11Y-30)

**Motion and zoom**
- `prefers-reduced-motion: reduce` stops spinners, pulses, transitions and smooth scrolling. Chart animation is off for everyone. The dashboard clock now updates by the minute with no seconds: an element that changes every second is hard to read and cannot be paused, so the ticking clock (an earlier design choice, not a requirement) was removed. (A11Y-31)
- Pages work at **200% zoom** (a 640 px wide window) and at **400%** (320 px): no sideways scrolling, headings fit and are at least 16 px, and zooming is not blocked in the viewport settings. (A11Y-32)
- Tap targets are at least 44 px on touch-sized screens (from an earlier stage).

**Keyboard-only journeys** (no mouse events at all; the test fails if one happens). (A11Y-33)
1. Sign in with the keyboard.
2. Upload a donation (opening the file chooser with Space), review it, add a new donor and confirm it.
3. Approve one shipment, then edit another (the edit form takes focus).
4. Submit a shortage report at 375 px wide.
5. Open and close a dialog and end where you started.

## Decisions

- **Warnings stay quiet.** An empty `role="alert"` is kept next to fields that can show an error so the message is announced when it appears.
- **The browser's own controls.** Date fields have several focus stops (month, day, year, the calendar button) inside one element. The focus-ring test judges the first stop; the calendar button draws the browser's own ring.
- **Native over custom.** Dialogs, details, selects and date pickers are the browser's own, with focus and Escape handling added only where the tests showed a gap.

## Not covered

- No manual testing with a screen reader (VoiceOver, NVDA, JAWS) has been done; the checks are automated and read the same accessibility tree those tools use, but that is not the same as listening to the page. A manual pass before go-live is recommended.
- Colour contrast is checked by axe on the pages and states it scans, not on every possible state.
- The app is English only; there are no captions or audio.
- Charts are summarised in text and as tables; the pictures themselves are not described beyond that.
- WCAG level AAA and the extra success criteria of WCAG 2.2 are not targeted (2.2's focus-appearance rule is met in practice by the 3 px outline).
