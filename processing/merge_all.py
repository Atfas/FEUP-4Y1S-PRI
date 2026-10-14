import json


def strip_name_whitespace(value):
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if (key == "name" or key == "title" or key.endswith("_name")) and isinstance(nested_value, str):
                value[key] = nested_value.strip()
            else:
                strip_name_whitespace(nested_value)
    elif isinstance(value, list):
        for item in value:
            strip_name_whitespace(item)


def merge_data(cards, pokemon, artists, expansions):
    new_cards = []
    for card in cards:
        pokemon_ref = card.get("pokemon", [])
        for pk in pokemon_ref:
            key = pk.get("id")
            pk.update(next((p for p in pokemon if p["id"] == key), {}))
            
            pk.pop("id", None)
            pk.pop("cards", None)
            pk.pop("has_page", None)

        print_ref = card.get("prints", [])
        for pr in print_ref:
            key = pr.get("set_id")
            # take out expansion id, and add an object with the full expansion data object
            pr.pop("set_id", None)
            pr["expansion"] = next((e for e in expansions if e["id"] == key), {})
            
            # delete fields that are not needed in expansion
            
            artist_key = pr.get("artist_id")
            pr.pop("artist_id", None)
            pr["artist"] = next((a for a in artists if a["id"] == artist_key), {})
            
            # same for artist, delete fields that are not needed
            
        card.pop("artists", None)
        card.pop("expansions", None)
        new_cards.append(card)
    return new_cards

def clean_cards(cards):
    cleaned_cards = []
    for card in cards:
        raw = card.get("kind")
        if isinstance(raw, str):
            raw = raw.replace("megaex", "mega ex")
            raw = raw.replace("magmaex", "magma ex")
            raw = raw.replace("aquaex", "aqua ex")
            raw = raw.replace("plasmaex", "plasma ex")
            raw = raw.replace("rocketex", "rocket ex")
            raw = raw.replace("primalex", "primal ex")
            card["kind"] = raw

        print_ref = card.get("prints", [])
        for pr in print_ref:
            expansion = pr.get("expansion", {})
            expansion.pop("cards", None)
            expansion.pop("has_page", None)
            expansion.pop("id", None)
            
            artist = pr.get("artist")
            artist.pop("cards", None)
            artist.pop("id", None)
            artist.pop("has_page", None)
        cleaned_cards.append(card)
    strip_name_whitespace(cleaned_cards)
    return cleaned_cards

def main():
    cards = json.load(open("search/cards.json", encoding="utf-8"))
    pokemon = json.load(open("search/pokemon.json", encoding="utf-8"))
    artists = json.load(open("search/artists.json", encoding="utf-8"))
    expansions = json.load(open("search/expansions.json", encoding="utf-8"))
    merged_cards = merge_data(cards, pokemon, artists, expansions)
    
    cleaned_cards = clean_cards(merged_cards)
    
    # save to databank.json
    with open("search/databank.json", "w", encoding="utf-8") as f:
        json.dump(cleaned_cards, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()