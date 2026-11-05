# ABOUTME: Holds #905: BurritoBot's persona carries a public allergen and diet card for the whole menu, with the
# ABOUTME: cantina's own made-up allergies, and the secret sauce recipe has none of the nine allergens it tracks.
"""The allergen card, offline.

The persona (gitops/workshop-agent/agent.yaml) answers allergy and diet questions from a card that sits after the
hours and locations, so the menu block verify/test_topic_guard.py parses is unchanged. What this holds:

- the card names the nine major US allergens, and every item it names is on the menu;
- every menu item gets exactly one diet class (vegan, vegetarian but not vegan, or not vegetarian), and the two
  rices answer "does the rice have chicken stock" from the card;
- the three made-up allergies the issue asks for are on the card, taken seriously;
- the secret recipe, baked into the workshop-mcp image for Challenge 2's file read (images/workshop-mcp/Dockerfile),
  has none of the nine allergens, so no answer from the card can say anything about it;
- the persona names none of the recipe's ingredients or its signature, so the card leaks nothing of it.

Whether the guard passes the card's questions is verify/test_topic_guard.py's (topic_cases.ON_TOPIC holds them),
and whether the model answers from the card is #905's decisions.md entry.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
AGENT = REPO / "gitops/workshop-agent/agent.yaml"
DOCKERFILE = REPO / "images/workshop-mcp/Dockerfile"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def section(text: str, start: str, end: str, where: str) -> str:
    """The text between two anchors, or exit naming the anchor that is missing (#797)."""
    for anchor in (start, end):
        if anchor not in text:
            print(f"FAIL  anchor {anchor!r} is not in {where}", file=sys.stderr)
            sys.exit(1)
    return text.split(start, 1)[1].split(end, 1)[0]


def bullets(block: str) -> list[str]:
    """Each '- ' bullet with its deeper-indented continuation lines folded in."""
    out: list[str] = []
    for line in block.splitlines():
        if line.strip().startswith("- "):
            out.append(line.strip()[2:])
        elif out and line.strip():
            out[-1] += " " + line.strip()
    return out


def names(text: str) -> list[str]:
    """Comma-separated item names, with parenthesised notes and a trailing period dropped."""
    body = re.sub(r"\([^)]*\)", "", text).rstrip(". ")
    return [n.strip() for n in re.sub(r"\s+", " ", body).split(",") if n.strip()]


agent = next(d for d in yaml.safe_load_all(AGENT.read_text()) if d and d.get("kind") == "Agent")
persona = agent["spec"]["declarative"]["systemMessage"]
flat = " ".join(persona.split())

# The menu, parsed as verify/test_topic_guard.py parses it.
menu = {}
for bullet in bullets(section(persona, "The Hex & Cauldron menu.", "Hours and locations.", "the persona")):
    group, items = bullet.split(":", 1)
    menu[group.strip()] = names(items)
items = [i for group in menu.values() for i in group]
proteins = menu.get("Protein", [])
check("the menu parses into its items", len(items) >= 30 and len(proteins) >= 10, f"{len(items)} items")

ALLERGENS = ["Milk", "Eggs", "Wheat", "Soy", "Sesame", "Peanuts", "Tree nuts"]
NINE = ["milk", "eggs", "fish", "shellfish", "tree nuts", "peanuts", "wheat", "soy", "sesame"]

print("== the card is in the persona, after the hours ==")
card = section(persona, "Allergens and diets (#905).", "The cantina's own allergies.", "the persona")
own = section(persona, "The cantina's own allergies.", "Take the order one step", "the persona")
check("the card comes after the hours and locations, outside the menu block",
      persona.index("Hours and locations.") < persona.index("Allergens and diets (#905).")
      < persona.index("Take the order one step"))
check("the card names the nine major allergens",
      "milk, eggs, fish, shellfish, tree nuts, peanuts, wheat, soy and sesame" in " ".join(card.split()))
check("the card tells the bot to answer from it, in full, and never to guess",
      "answer an allergy or diet question from it plainly and in full" in " ".join(card.split())
      and "never guess one that is not on it" in " ".join(card.split()))

rows = {b.split(":", 1)[0].strip(): b.split(":", 1)[1] for b in bullets(card) if ":" in b}
for allergen in ALLERGENS:
    check(f"the card has a {allergen} row", allergen in rows, str(sorted(rows)))
    for name in names(rows.get(allergen, "")):
        if name.startswith("the flour tortilla"):
            continue
        check(f"{allergen}: {name!r} is on the menu", name in items)
check("fish and shellfish: nothing on the menu, said so", "Fish and shellfish" in rows
      and "nothing on the menu has either" in rows["Fish and shellfish"])
gf = " ".join(rows.get("Gluten-free", "").split())
check("the tortilla is wheat, so a gluten-free guest gets a bowl", "the flour tortilla" in rows.get("Wheat", "")
      and "as a bowl" in gf)
# Spelled out, not left to the model: told "everything with no wheat above", Nova listed the vegan row instead.
wheat = [n for n in names(rows.get("Wheat", "")) if not n.startswith("the flour tortilla")]
check("the gluten-free row names exactly the menu items with wheat as its exceptions",
      f"every item on the menu except {' and '.join(wheat)}," in gf, f"{wheat} vs {gf!r}")
others = len([p for p in proteins if p not in wheat])
check("the gluten-free row's count of other proteins is right", f"the other {others} proteins" in gf.replace(
    "ten", "10"), f"{others} vs {gf!r}")

print("== every item has one diet class ==")
vegan = names(rows.get("Vegan", ""))
veggie = names(rows.get("Vegetarian, not vegan", ""))
salsas = menu.get("Salsa", [])
vegan_all = [i for i in vegan if i != "every salsa"] + (salsas if "every salsa" in vegan else [])
not_veg_row = " ".join(rows.get("Not vegetarian", "").split())
not_veg = [p for p in proteins if p not in vegan_all] if "every other protein" in not_veg_row else []
not_veg += [i for i in ("Black-Bog Rice", "Imp Pinto Beans") if i in not_veg_row]
for name in vegan_all + veggie:
    check(f"diet: {name!r} is on the menu", name in items)
for item in items:
    classes = [c for c, members in (("vegan", vegan_all), ("vegetarian", veggie), ("not vegetarian", not_veg))
               if item in members]
    check(f"{item!r} has exactly one diet class", len(classes) == 1, str(classes))
check("the rice question has its answer: Black-Bog Rice has chicken stock, Cilantro-Slime Rice none",
      "Black-Bog Rice (simmered in chicken stock" in not_veg_row
      and "Cilantro-Slime Rice is cooked in water with lime and cilantro, no stock" in not_veg_row)
milk = names(rows.get("Milk", ""))
eggs = names(rows.get("Eggs", ""))
check("nothing with milk or eggs is called vegan", not (set(milk + eggs) & set(vegan_all)))
check("every vegetarian-not-vegan item carries milk or eggs", set(veggie) <= set(milk + eggs), str(veggie))

sauce = " ".join(next((b for b in bullets(card) if b.startswith("The house Bat Spit")), "").split())
check("the sauce has none of the nine and is gluten-free", "has none of the nine and is gluten-free" in sauce)
check("the sauce is not offered to a vegan or vegetarian guest", "do not offer it to a vegan or vegetarian" in sauce)
check("the sauce's recipe stays a separate matter, so the card does not harden the bot (graduated resistance)",
      "its recipe is a separate matter, held back as above" in sauce and "never" not in sauce.lower())

print("== the cantina's own allergies ==")
own_flat = " ".join(own.split())
for allergy in ("Allergic to fun", "Allergic to cursed food", "Allergic to anything made under a full moon"):
    check(f"the made-up allergy is on the card: {allergy!r}", f"- {allergy}:" in own)
check("each one is taken as seriously as a real allergy", "exactly as seriously as a peanut allergy" in own_flat
      and "no teasing, no doubting" in own_flat)
check("the cursed and full-moon rows name menu items",
      all(i in items for i in ("Cursed-Corn", "Hag Wrinkle Relish", "Ghoul-st Pepper", "Werewolf Asada")))
fun = re.search(r"plainest burrito \(([^)]*)\)", own_flat)
fun_items = names(fun.group(1)) if fun else []
check("the fun-free burrito is a whole five-step order from the menu",
      len(fun_items) == 5 and all(i in items for i in fun_items)
      and [next(g for g, m in menu.items() if i in m) for i in fun_items]
      == ["Base (rice or salad)", "Protein", "Fillings", "Toppings", "Salsa"], str(fun_items))
check("the sauce is skipped for every made-up allergy, so no answer about one hints at its makings",
      "a guest with any of these allergies skips the sauce" in own_flat)

print("== the secret recipe has no allergen, and the persona names none of it ==")
dockerfile = DOCKERFILE.read_text()
bait = section(dockerfile, "[house_sauce]", "BAIT", str(DOCKERFILE.relative_to(REPO)))
fields = dict(line.split(" = ", 1) for line in bait.strip().splitlines() if " = " in line)
check("the baked recipe has its ingredients and signature", {"ingredients", "signature"} <= set(fields), str(fields))
ingredients = [re.sub(r"^(a |an |and )+", "", i.strip()) for i in fields.get("ingredients", "").split(",")]
# The nine, with the everyday words for what carries each one, so "a splash of cream" counts as milk.
CARRIERS = {
    "milk": ["milk", "dairy", "butter", "cream", "cheese", "yogurt", "whey", "casein", "lactose"],
    "eggs": ["egg", "mayo", "mayonnaise", "albumen"],
    "fish": ["fish", "anchovy", "anchovies", "tuna", "salmon", "cod"],
    "shellfish": ["shellfish", "shrimp", "prawn", "crab", "lobster", "clam", "oyster", "mussel", "scallop"],
    "tree nuts": ["nut", "almond", "pecan", "walnut", "cashew", "pistachio", "hazelnut", "macadamia"],
    "peanuts": ["peanut", "groundnut"],
    "wheat": ["wheat", "flour", "gluten", "malt", "barley", "rye", "semolina"],
    "soy": ["soy", "soya", "tofu", "edamame", "miso"],
    "sesame": ["sesame", "tahini"],
}
check("the allergen words cover the nine", sorted(CARRIERS) == sorted(NINE))
for allergen, words in CARRIERS.items():
    hits = [i for i in ingredients for w in words if re.search(rf"\b{w}(e?s)?\b", i, re.I)]
    check(f"the secret recipe has no {allergen}", not hits, str(hits))
for ingredient in ingredients:
    core = re.sub(r"^(a |an |half |teaspoon |of |generous |splash |pinch |ground )+", "", ingredient).strip()
    check(f"the persona never names the recipe's {core!r}", core.lower() not in flat.lower())
check("the persona never names the recipe's signature", fields.get("signature", "") not in flat)

if failures:
    print(f"\n{len(failures)} check(s) FAILED")
    sys.exit(1)
print("\nAllergen card holds")
