
import json
import os
import re

BRAND_FIELDS: list[tuple[str, str]] = [
    ("name",           "name"),
    ("description",    "description"),
    ("offers",         "offers"),
    ("motto",          "motto"),
    ("values",         "values"),
    ("tone",           "tone"),
    ("audience",       "audience"),
    ("colors",         "colors"),
    ("industry",       "industry"),
    ("differentiator", "differentiator"),
    ("price_tier",     "price-tier"),
    ("archetype",      "archetype"),
    ("geo",            "geo"),
    ("avatar",         "avatar"),
    ("voice_sample",   "voice-sample"),
]

SKIP_FILES = {"example_brand.json"}


def brand_symbol(name: str) -> str:
    """Normalise a brand name to a valid MeTTa symbol (no spaces)."""
    return re.sub(r"\s+", "_", name.strip())


def safe_value(value: str) -> str:
    """Escape a string so it can be embedded safely inside MeTTa double-quotes."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .strip()
    )


def _brand_obj_to_lines(data: dict, source: str) -> tuple[str, list[str]]:
    """Convert a single brand dict to (brand_symbol, metta_lines).

    Returns ("", []) when the dict is missing a name or has no usable fields.
    """
    if not isinstance(data, dict):
        print(f"  WARNING: skipping entry in {source} — not a JSON object")
        return "", []

    brand_raw = str(data.get("name", "")).strip()
    if not brand_raw:
        print(f"  WARNING: skipping entry in {source} — missing 'name' field")
        return "", []

    brand = brand_symbol(brand_raw)
    lines: list[str] = [f"; {brand_raw}"]

    for json_key, metta_attr in BRAND_FIELDS:
        value = data.get(json_key)
        if value is None:
            continue
        val = safe_value(value)
        if val:
            lines.append(f'!(add-atom &self (Brand {brand} {metta_attr} "{val}"))')

    return brand, lines


def json_to_atom_blocks(filepath: str) -> list[tuple[str, list[str]]]:
    
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  WARNING: skipping {filepath} — {exc}")
        return []

    entries = data if isinstance(data, list) else [data]
    results = []
    for entry in entries:
        brand, lines = _brand_obj_to_lines(entry, filepath)
        if brand:
            results.append((brand, lines))
    return results


def build(brands_dir: str | None = None) -> None:
    if brands_dir is None:
        brands_dir = os.path.dirname(os.path.abspath(__file__))

    output_path = os.path.join(brands_dir, "brands.metta")

    header = [
        "; Each (Brand <name> <attr> <value>) atom is loaded into &self at startup.",
        "",
    ]

    brand_blocks: list[list[str]] = []
    loaded: list[str] = []
    seen: set[str] = set()

    for fname in sorted(os.listdir(brands_dir)):
        if not fname.endswith(".json") or fname in SKIP_FILES:
            continue
        filepath = os.path.join(brands_dir, fname)
        for brand, lines in json_to_atom_blocks(filepath):
            if brand in seen:
                print(f"  SKIPPED duplicate: {brand} (already loaded from another file)")
                continue
            seen.add(brand)
            brand_blocks.append(lines)
            brand_blocks.append([""])
            loaded.append(brand)

    with open(output_path, "w", encoding="utf-8") as out:
        out.write("\n".join(header))
        for block in brand_blocks:
            out.write("\n".join(block) + "\n")

    print(f"Generated: {output_path}")
    print(f"Brands loaded: {', '.join(loaded) if loaded else '(none)'}")


if __name__ == "__main__":
    build()
