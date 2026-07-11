# Research Spike: Chipotle menu → Hex & Cauldron witchy mapping

Date: 2026-07-11. Purpose: expand the BurritoBot "Hex & Cauldron" menu (the left-rail
build-your-burrito board) so every Chipotle menu item has a witchy equivalent, per Michael + Whitney.
Sources (retrieved 2026-07-11): usafoodjournal.com Chipotle menu (updated 2026-07-09), chipotlemenus.us.
The menu lives in two places that must stay in sync: `gitops/ai-layer/resources.yaml` (the Agent
systemMessage) and `gitops/ai-layer/web/burritbot.html` (the left-rail chips).

## Current Hex & Cauldron menu (5-step build)
- **Protein:** Bogbacoa, Croak-nitas, Sorcerizo, Soot-Fritas, Toe-Fu, Fae-jita Veggies
- **Base:** Cilantro-Slime Rice, Black-Bog Rice, Graveyard Greens
- **Fillings:** Black Bane Beans, Imp Pinto Beans, Kelpie Queso, Ogre Snot Guac
- **Salsa:** Pixie-o de Gallo (mild), Cursed-Corn (medium), Dragon's Blood (hot), Ghoul-st Pepper (ghost)
- **Toppings:** Sour Scream, Crow's-Foot Cilantro, Hag Wrinkle Relish, Tardigrade Crunch
- **Sides:** Toad-illa Chips. House sauce: Bat Spit Amazing Awesome Sauce.

## Authoritative Chipotle menu (2026)
- **Proteins:** Adobo Chicken, Steak, Barbacoa, Carnitas, Carne Asada, Sofritas (tofu), Chicken al Pastor,
  Chipotle Honey Chicken, Smoked Brisket, Veggie/Fajita.
- **Rice:** Cilantro-Lime White, Brown. **Beans:** Black, Pinto.
- **Salsa:** Fresh Tomato (mild), Roasted Chili-Corn (medium), Tomatillo-Green (medium), Tomatillo-Red (hot).
- **Free toppings:** Fajita Veggies, Romaine Lettuce, Monterey Jack Cheese (shredded), Sour Cream.
  **Premium:** Guacamole (+), Queso Blanco (+).
- **Sides:** Chips, Chips & Guac, Chips & Queso, Chips & each salsa, side of guac/queso/cheese/rice/beans.
- **Drinks:** Fountain, Organic Lemonade, Peach Lemonade, Agua Fresca, Fresh Brewed Tea, Topo Chico,
  Bottled Water, Apple Juice, Organic Milk.
- **Formats:** Burrito, Bowl, Soft/Crispy Tacos, Quesadilla, Salad, Kids meals, Lifestyle bowls (Keto,
  Vegan, Whole30, Balanced Macros, Wholesome).

## Gaps + proposed witchy names (the mapping)

### Proteins — the biggest gap (we're missing CHICKEN, the #1 Chipotle item)
| Chipotle | Have? | Proposed witchy name |
|---|---|---|
| Barbacoa | ✅ Bogbacoa | — |
| Carnitas | ✅ Croak-nitas | — |
| Sofritas (tofu) | ✅ Soot-Fritas (+ Toe-Fu bonus) | — |
| Veggie/Fajita | ✅ Fae-jita Veggies | — |
| (Chorizo, Chipotle-discontinued) | ✅ Sorcerizo | keep as house bonus |
| **Adobo Chicken** | ❌ | **Cluck-a-cadabra** (alt: Voodoo-bo Chicken) |
| **Steak** | ❌ | **Wraith Stake** (steak→stake) |
| **Carne Asada** | ❌ | **Cadaver Asada** (alt: Cairn Asada) |
| **Chicken al Pastor** | ❌ | **Al Ghastor** (al Pastor + ghast) |
| **Chipotle Honey Chicken** | ❌ | **Honeyed Hex Hen** |
| **Smoked Brisket** | ❌ | **Bonfire Brisket** (on-theme with "watch it burn") |

### Salsa
| Chipotle | Have? | Proposed |
|---|---|---|
| Tomatillo-Green (medium) | ❌ | **Goblin-Green** (alt: Bog-atillo Verde) |

### Toppings
| Chipotle | Have? | Proposed |
|---|---|---|
| Monterey Jack Cheese (shredded) | ❌ (Kelpie Queso is liquid queso, distinct) | **Grated Ghoul Cheese** |
| Romaine Lettuce | ~ (Graveyard Greens is the base; add as topping) | **Wraith-maine Lettuce** (optional) |
| Fajita Veggies as topping | ~ (covered by the protein) | reuse Fae-jita Veggies |

### Sides (optional additions)
- **Toad-illa Chips & Ogre Snot Guac**, **Toad-illa Chips & Kelpie Queso** (the classic combos).

### Drinks (all missing; optional, adds flavor)
- Fountain → **Bubbling Brew** · Lemonade → **Witch's Brew Lemonade** · Peach Lemonade → **Peach Poltergeist**
  · Agua Fresca → **Eye-of-Newt Agua Fresca** · Tea → **Newt-tea (Fresh-Brewed)** · Topo Chico → **Cauldron Fizz**
  · Bottled Water → **Moon Water** · Milk (kids) → **Bat Milk**.

## Recommendation
Minimum to "cover the real menu": add the **6 missing proteins** (chicken is the must-have), the
**tomatillo-green salsa**, and **shredded cheese**. Drinks + formats (bowls/tacos/quesadilla/kids/
lifestyle) are nice-to-have flavor and a bigger change to the 5-step flow. The menu is a static board
today; keep resources.yaml and burritbot.html in sync (both call that out in comments).
