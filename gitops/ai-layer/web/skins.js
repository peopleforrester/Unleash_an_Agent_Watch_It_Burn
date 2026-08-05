// ABOUTME: VTT skin definitions (data only). Each skin is a set of brand tokens + CSS-variable overrides
// ABOUTME: applied by skin.js to the terminal chrome (lab.html + console.html). Add a new skin = add a key.
//
// This is the portable theme layer for the student-facing VTT chrome. It does NOT touch the BurritoBot
// storefront app (burritbot.html) or any functional BurritoBot references; only the terminal + front-door
// chrome (header brand, titles, favicon, accent palette). Switch the active skin in active-skin.js.
//
// Adding a skin: copy a block, change the key + tokens. `vars` keys are the CSS custom properties the
// chrome already reads (--dd = lab header bg, --accent = lab accent, --r3 = lab pill/role chip,
// --orange = console accent). Any var you omit keeps the page default.
window.WITB_SKINS = {
  // The current/default skin, captured verbatim from the existing chrome. Selecting this = no visual change.
  burritobot: {
    label: "BurritoBot (Watch It Burn)",
    brandName: "Watch It Burn",
    brandEmoji: "🔥",              // 🔥
    favicon: "🔥",                 // 🔥
    titleLab: "Your cluster shell — Watch It Burn",
    titleConsole: "Watch It Burn — Your Cluster",
    h1Console: "🔥 Watch It Burn — your cluster",
    vars: { "--dd": "#632CA6", "--accent": "#8A00D6", "--r3": "#7a3ff2", "--orange": "#ffb454" }
  },
  // Temporary Accenture skin. #A100FF is the Accenture brand purple already carried in the chrome as
  // --acn; the mark is a nod to Accenture's ">" logo accent. Text-only (no logo asset) on purpose.
  accenture: {
    label: "Accenture",
    brandName: "Accenture",
    brandEmoji: "›",                    // › (Accenture ">" logo nod)
    favicon: "🟣",                 // 🟣
    titleLab: "Your cluster shell — Accenture",
    titleConsole: "Accenture — Your Cluster",
    h1Console: "› Accenture — your cluster",
    vars: { "--dd": "#A100FF", "--accent": "#A100FF", "--r3": "#7500C0", "--orange": "#A100FF" }
  }
};
