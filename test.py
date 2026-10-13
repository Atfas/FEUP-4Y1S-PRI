import json, random

cards = json.load(open("search/cards.json", encoding="utf-8"))
card = cards[0]

# print the full shape of the json objects
print(json.dumps(card, indent=2, ensure_ascii=False))