# Guest Console UI Review

- Date: 2026-10-07
- Preview: `http://localhost:8765`
- Verdict: Pass for the MVP screens at desktop, tablet, and mobile widths.

## Viewport review

| Viewport | Screenshot | Result |
| --- | --- | --- |
| 1280 × 800 | [Desktop](screenshots/guest-console-desktop.png) | Conversation and department panel fit side by side; no horizontal overflow. |
| 768 × 1024 | [Tablet](screenshots/guest-console-tablet.png) | Panels stack into one column and remain readable. |
| 375 × 667 | [Mobile](screenshots/guest-console-mobile.png) | Content uses a single column, controls fit the viewport, and no horizontal overflow was visible. |

## Accessibility and interaction

- Keyboard focus was moved to the message field and send control. The composer focus indicator remained visible; see [keyboard focus screenshot](screenshots/guest-console-keyboard-focus.png).
- The message field has a programmatic label. Conversation history uses a polite live region; the error message uses `role="alert"`; Agent Card loading and partial failure messages use status regions.
- Muted body text uses `#5f6d66` (about 5.4:1 against white). The gold focus outline uses `#c18137` (about 3.2:1 against white). Both meet the relevant WCAG AA contrast thresholds for their use.
- The mobile and desktop views were inspected after loading the Agent Cards. Agent names and descriptions are readable, and duplicate generic skill text is omitted.
- The send control's keyboard focus and pointer hover were checked. No guest request was submitted during this review.

## Notes

- The app uses in-memory sessions. A browser session left over from a previous server run can request a session ID that no longer exists; the app creates a fresh session. A clean browser origin loaded without console errors.
- Screen-reader announcements were checked through the accessibility tree and semantic markup, not with a physical screen reader.
