# Design system — current development slice

The shared stylesheet `static/css/site.css` is used by every current page. This is a partial system, not a complete admin or clinical UI kit. Home, search (including cursor continuation and stale state), presentation detail, price-status and about pages share navigation, search, footer, cards, spacing, states and typography. The development-only staff queue, upload, preliminary review and login share the same visual tokens, with supplemental `static/css/staff.css`. There are no production admin components, modals, charts or mobile app components yet.

## Direction and palette comparison

UI UX Pro Max's healthcare/clinic palette suggests calm cyan/teal and health green; its pharmacy palette uses green and blue. Three directions considered (contrast figures are WCAG relative-luminance calculations for the stated text/background pair, not an accessibility certification):

| Direction | Primary on white | Ratio | Assessment |
|---|---|---:|---|
| A: pharmaceutical teal | `#147d6f` on `#ffffff` | 5.01:1 | Selected; healthcare identity without retail-pharmacy or financial cues. |
| B: clinical blue/emerald | `#1d4e89` on `#ffffff` | 8.39:1 | Strong contrast, but more institutional and less distinctive for the current brief. |
| C: scientific green | `#186a4a` on `#ffffff` | 6.56:1 | Clear and calm but may skew toward pharmacy retail. |

Semantic CSS variables define ink, brand, backgrounds, surfaces, border, muted, success, warning, error, shadow and radius. Text contrast, all states, component focus and real-device accessibility still require a systematic audit. Avoid warning/error colors as decoration; semantic states must include text, not color alone.

## Typography and layout

Self-hosted [Vazirmatn](https://github.com/rastikerdar/vazirmatn) variable WOFF2; its SIL OFL licence is included in `static/fonts/OFL.txt`. `font-display: swap` and fallbacks keep text visible. SVG icons are local, no third-party tracking or runtime assets. Persian RTL is default; mixed terms use `bdi`/`dir=auto`. The shared container, search form, navigation, cards, buttons, empty states and responsive CSS are in `static/css/site.css`; reduced-motion and keyboard focus styles are present. Width breakpoints are 700px and 950px. Styles adapt to the viewport, but actual browser/device regression and screen-reader tests are still required.
