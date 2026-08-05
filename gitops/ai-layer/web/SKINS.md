# VTT skins

A portable theme layer for the student-facing terminal chrome (`lab.html` + `console.html`). Switch the
whole look with one line, now or in the future. The BurritoBot look is captured as the default skin, so
this is additive: with no change, nothing looks different.

Scope is the **VTT chrome only**: header brand, page titles, favicon, and the accent palette. It does
**not** touch the BurritoBot storefront (`burritbot.html`) or any functional "BurritoBot" references
(the button that opens the app, the challenge instructions). The app stays BurritoBot; only the frame
around the terminal reskins.

## Files

| File | Role |
|---|---|
| `skins.js` | Skin definitions (data). `burritobot` (captured default) and `accenture`. Add skins here. |
| `active-skin.js` | **The knob.** One line: `window.WITB_ACTIVE_SKIN = "..."`. |
| `skin.js` | Applier. Sets palette vars on `<html>` (no flash) + brand text/title/favicon on load. |

All three are in the `console-src` ConfigMap and load in the `<head>` of both pages, in that order.

## Apply a skin (now or later)

1. Edit `active-skin.js` and set the key, e.g. `window.WITB_ACTIVE_SKIN = "accenture";`
2. Commit. **Fresh clusters** pick it up at provision, no other step.
3. **A cluster that is already running**: the console ConfigMap has a fixed name (no content hash), so
   bounce the console pod to load the change:
   ```
   kubectl -n agent delete pod -l app.kubernetes.io/name=console
   ```

## Roll back

Set `active-skin.js` back to `window.WITB_ACTIVE_SKIN = "burritobot";` (fresh cluster or the same pod
bounce). That is the whole rollback.

## Add a new skin (e.g. a client brand)

In `skins.js`, copy a block and change the key + tokens:

```js
window.WITB_SKINS = {
  // ...
  clientx: {
    label: "Client X",
    brandName: "Client X",
    brandEmoji: "▣",
    favicon: "▣",
    titleLab: "Your cluster shell — Client X",
    titleConsole: "Client X — Your Cluster",
    h1Console: "▣ Client X — your cluster",
    vars: { "--dd": "#0057B8", "--accent": "#0057B8", "--r3": "#003E82", "--orange": "#0057B8" }
  }
};
```

`vars` keys are the CSS custom properties the chrome already reads:

| Var | What it colors |
|---|---|
| `--dd` | `lab.html` header background |
| `--accent` | `lab.html` accent (copy buttons, step numbers, hover) |
| `--r3` | `lab.html` pill + role chip |
| `--orange` | `console.html` accent (h1, cost, active tab, headings) |

Omit any var to keep the page default. Then point `active-skin.js` at the new key.

## Notes

- Text-only by design (emoji/mark, no logo files) so nothing brand-specific lands in the public repo's
  binary history. Add an inline SVG wordmark in a skin's chrome hook if you want more than text.
- If a temporary client skin should never reach `main`, keep it on `staging` (or a branch) and revert
  before promoting.
