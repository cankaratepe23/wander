"""Demo data for local development: ``WANDER_DEV_MODE=true python -m app.seed``.

Fills an empty database with two people and about thirty ideas across the world, so the globe's piles can be
seen and tested before the enrichment pipeline exists. It refuses to run outside dev mode, or on a
database that already has ideas.
"""

import sys

from sqlalchemy import func, select

from app.config import get_settings
from app.db import make_engine, make_sessionmaker
from app.migrate import upgrade_to_head
from app.models import Heart, Idea, IdeaPlace, Place, User

# fmt: off
# (place, lat, lng, city, region, country, code)
P = {
    "lisbon": ("Lisbon", 38.722, -9.139, "Lisbon", "Lisbon", "Portugal", "PT"),
    "porto": ("Porto", 41.150, -8.611, "Porto", "Porto", "Portugal", "PT"),
    "sintra": ("Sintra", 38.800, -9.388, "Sintra", "Lisbon", "Portugal", "PT"),
    "lagos": ("Lagos", 37.102, -8.674, "Lagos", "Algarve", "Portugal", "PT"),
    "benagil": ("Benagil cave", 37.087, -8.426, "Lagoa", "Algarve", "Portugal", "PT"),
    "douro": ("Douro Valley", 41.162, -7.789, "Peso da Régua", "Vila Real", "Portugal", "PT"),
    "kas": ("Kaş", 36.202, 29.637, "Kaş", "Antalya", "Türkiye", "TR"),
    "kalkan": ("Kalkan", 36.265, 29.414, "Kaş", "Antalya", "Türkiye", "TR"),
    "oludeniz": ("Ölüdeniz", 36.550, 29.120, "Fethiye", "Muğla", "Türkiye", "TR"),
    "cappadocia": ("Göreme", 38.643, 34.830, "Göreme", "Nevşehir", "Türkiye", "TR"),
    "istanbul": ("Karaköy", 41.022, 28.977, "Istanbul", "Istanbul", "Türkiye", "TR"),
    "amalfi": ("Amalfi", 40.634, 14.603, "Amalfi", "Campania", "Italy", "IT"),
    "dolomites": ("Seceda", 46.600, 11.722, "Ortisei", "Trentino-South Tyrol", "Italy", "IT"),
    "kazbegi": ("Kazbegi", 42.658, 44.643, "Stepantsminda", "Mtskheta-Mtianeti", "Georgia", "GE"),
    "iceland_s": ("Skógafoss", 63.532, -19.511, "Skógar", "Southern Region", "Iceland", "IS"),
    "iceland_n": ("Mývatn", 65.603, -16.996, "Reykjahlíð", "Northeastern Region", "Iceland", "IS"),
    "lofoten": ("Reine", 67.932, 13.089, "Reine", "Nordland", "Norway", "NO"),
    "copenhagen": ("Copenhagen", 55.676, 12.568, "Copenhagen", "Capital Region", "Denmark", "DK"),
    "kyoto": ("Arashiyama", 35.009, 135.667, "Kyoto", "Kyoto", "Japan", "JP"),
    "kyoto_c": ("Nishiki Market", 35.005, 135.765, "Kyoto", "Kyoto", "Japan", "JP"),
    "oaxaca": ("Oaxaca", 17.073, -96.726, "Oaxaca", "Oaxaca", "Mexico", "MX"),
    "cdmx": ("Roma Norte", 19.419, -99.162, "Mexico City", "Mexico City", "Mexico", "MX"),
    "cancun": ("Isla Mujeres", 21.232, -86.731, "Isla Mujeres", "Quintana Roo", "Mexico", "MX"),
    "zanzibar": ("Stone Town", -6.162, 39.188, "Zanzibar City", "Zanzibar", "Tanzania", "TZ"),
}

# (title, category, place, who, hearts, best, good, budget, length, summary)
IDEAS = [
    ("Pastéis de nata crawl", "food", "lisbon", 0, 2, [4, 5, 6], [9, 10], 1, "1 day", "Manteigaria vs Pastéis de Belém, settled once and for all."),
    ("Tascas in Alfama", "food", "lisbon", 1, 2, [5, 6], [4, 9], 2, "1 evening", "Fado and grilled sardines in tiny family places."),
    ("Time Out Market", "food", "lisbon", 0, 1, [], [], 2, "2 hours", "Busy, but a good first-night sampler."),
    ("Francesinha in Porto", "food", "porto", 1, 2, [5, 6], [9], 1, "1 meal", "The sandwich, at Café Santiago."),
    ("Douro wine train", "wine", "douro", 0, 2, [9, 10], [5, 6], 3, "1 day", "Harvest season, river views, quinta tastings."),
    ("Pena Palace early entry", "culture", "sintra", 1, 1, [4, 5], [10], 2, "1 day", "Go at opening, before the tour buses."),
    ("Ponta da Piedade by kayak", "beach", "lagos", 0, 2, [6, 7], [5, 9], 2, "half a day", "Sea arches and grottoes at golden hour."),
    ("Benagil cave", "beach", "benagil", 1, 1, [6, 7, 8], [5, 9], 2, "half a day", "Swim or paddle in, never the boat tours."),
    ("Algarve cliff walk", "hiking", "lagos", 0, 2, [4, 5], [9, 10], 1, "1 day", "Seven Hanging Valleys trail."),
    ("Lycian Way: Kaş to Kalkan", "hiking", "kas", 0, 2, [9, 10], [4, 5], 2, "2–3 days", "Cliff paths, Lycian tombs and swimming coves."),
    ("Kalkan rooftop dinners", "food", "kalkan", 1, 1, [9], [5, 6], 3, "1 evening", "Sunset over the bay from the old town."),
    ("Ölüdeniz paragliding", "experience", "oludeniz", 1, 2, [5, 6], [9, 10], 3, "half a day", "Off Babadağ, over the blue lagoon."),
    ("Cappadocia balloons", "experience", "cappadocia", 0, 2, [4, 5], [9, 10], 4, "2 days", "Cave hotel and a sunrise flight."),
    ("Karaköy breakfast", "food", "istanbul", 1, 1, [4, 5], [10], 1, "1 morning", "Serpme kahvaltı, then the ferry."),
    ("Path of the Gods", "hiking", "amalfi", 1, 2, [5, 6], [9], 2, "1 day", "Bomerano to Nocelle, then down to Positano."),
    ("Lemon groves of Amalfi", "food", "amalfi", 0, 1, [5], [6], 2, "1 day", "Limoncello tasting, pasta al limone."),
    ("Seceda ridgeline", "hiking", "dolomites", 0, 1, [7, 8], [9], 2, "1 day", "Cable car up, slow walk down."),
    ("Rifugio hut-to-hut", "hiking", "dolomites", 0, 1, [7, 8], [], 2, "4 days", "Alta Via 1, first section."),
    ("Gergeti Trinity Church hike", "hiking", "kazbegi", 0, 2, [6, 7], [9], 1, "1 day", "Church under Mount Kazbek."),
    ("Khinkali in Stepantsminda", "food", "kazbegi", 1, 1, [6], [], 1, "1 meal", "Learn to eat them properly."),
    ("Skógafoss and the south coast", "nature", "iceland_s", 1, 2, [6, 7, 8], [9], 3, "3 days", "Waterfalls, black beaches, a glacier walk."),
    ("Mývatn nature baths", "wellness", "iceland_n", 0, 1, [2, 3], [9], 3, "1 day", "Northern lights season."),
    ("Ring Road, north half", "road trip", "iceland_n", 1, 2, [7], [6, 8], 3, "5 days", "Akureyri to Egilsstaðir."),
    ("Reine rorbu stay", "accommodation", "lofoten", 0, 1, [6, 7], [3], 4, "3 nights", "Red fishermen's cabins on stilts."),
    ("Copenhagen by bike", "city break", "copenhagen", 0, 1, [5, 6], [9], 3, "3 days", "Bakeries, harbour baths, Reffen."),
    ("Arashiyama bamboo at dawn", "nature", "kyoto", 1, 2, [4, 11], [5, 10], 3, "1 morning", "Before 7 am, then Ōkōchi Sansō."),
    ("Nishiki Market lunch", "food", "kyoto_c", 0, 2, [4, 11], [], 2, "2 hours", "Tamagoyaki and pickles."),
    ("Kyoto ryokan night", "accommodation", "kyoto", 1, 2, [11], [4], 4, "1 night", "Kaiseki dinner, onsen."),
    ("Gion lanterns", "culture", "kyoto", 0, 1, [4], [11], 1, "1 evening", "Hanamikoji after dark."),
    ("Mole in Oaxaca", "food", "oaxaca", 0, 2, [10, 11], [3], 2, "3 days", "Seven moles, a cooking class, mezcal."),
    ("Día de Muertos in Oaxaca", "festival", "oaxaca", 1, 2, [11], [], 2, "4 days", "Altars, comparsas, the cemeteries at night."),
    ("Tacos in Roma Norte", "food", "cdmx", 1, 1, [3, 4], [11], 1, "2 days", "Al pastor crawl and Contramar."),
    ("Isla Mujeres snorkel", "beach", "cancun", 0, 1, [12, 1, 2, 3], [4], 3, "3 days", "Golf carts, whale sharks in season."),
    ("Stone Town spice tour", "culture", "zanzibar", 1, 1, [6, 7, 8], [1, 2], 2, "2 days", "Then the east coast beaches."),
]
# fmt: on


def main() -> None:
    settings = get_settings()
    if not settings.dev_mode:
        sys.exit("refusing to seed: WANDER_DEV_MODE is not true")
    upgrade_to_head(settings.db_path)
    factory = make_sessionmaker(make_engine(settings.db_path))
    with factory() as db:
        if db.scalar(select(func.count(Idea.id))):
            sys.exit("refusing to seed: the database already has ideas")
        people = []
        for email, name in ((settings.dev_user_email, None), ("sam@localhost", "Sam")):
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(email=email, display_name=name or email.split("@")[0].title())
                db.add(user)
            people.append(user)
        places = {}
        for key, (name, lat, lng, city, region, country, code) in P.items():
            places[key] = Place(
                name=name,
                type="poi",
                lat=lat,
                lng=lng,
                city=city,
                region=region,
                country=country,
                country_code=code,
                geocoder="seed",
            )
            db.add(places[key])
        for title, cat, key, who, hearts, best, good, budget, length, summary in IDEAS:
            idea = Idea(
                title=title,
                category=cat,
                summary=summary,
                best_months=best,
                good_months=good,
                budget_level=budget,
                trip_length_hint=length,
                creator=people[who],
                ai_model="seed",
            )
            idea.links.append(IdeaPlace(place=places[key], role="primary"))
            db.add(idea)
            db.flush()
            for person in (people[who], people[1 - who])[:hearts]:
                db.add(Heart(idea_id=idea.id, user_id=person.id))
        db.commit()
    print(f"seeded {len(IDEAS)} ideas across {len(P)} places")


if __name__ == "__main__":
    main()
