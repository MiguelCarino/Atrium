#!/usr/bin/env python3
"""Build the launcher's place index: every town of 5,000+ people (GeoNames
cities5000, ~70k places), so typing a city's name suggests it on the map --
offline: what you type never leaves the machine.

    make-places.py          download GeoNames' current files, write the index

Writes ~/.local/share/launcher/places.tsv (and a README there with the
source and licence), one place per line:

    keys \\t name \\t state \\t country \\t population \\t lat \\t lon \\t timezone

`keys` are the place's names normalised as launcher.py normalises a query
(lower case, accents off, punctuation to spaces): its name, its ASCII name,
and its alternate names written in Latin letters ("ciudad de mexico",
"mexico city", "cdmx" for Mexico City). Left out on purpose: alternate names
of 3 letters or fewer (mostly airport codes -- "mex", "lax" would make an
ordinary search look like a place) and names in other scripts (nobody types
them on this keyboard, and they triple the file).

And ~/.local/share/launcher/airports.tsv, one airport with an IATA code per
line (large and medium ones, and small ones with scheduled flights; ~5k):

    CODE \t name \t city \t country \t rank \t lat \t lon \t city keys

rank: size (3 large, 2 medium, 1 small) * 2, plus 1 with scheduled
flights -- the launcher lists a city's airports by it, so "paris airports"
is CDG and Orly before Le Bourget (large, but business jets only).

Sources: https://download.geonames.org/export/dump/ -- cities5000.zip,
admin1CodesASCII.txt (state names), countryInfo.txt (country names);
GeoNames, CC BY 4.0. https://ourairports.com/data/ -- airports.csv;
OurAirports, public domain. Rerun whenever; a minute, ~20 MB down.
"""

import csv
import io
import os
import re
import sys
import unicodedata
import urllib.request
import zipfile

BASE = "https://download.geonames.org/export/dump/"
AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
AIRPORT_RANK = {"large_airport": 3, "medium_airport": 2, "small_airport": 1}
OUT_DIR = os.path.expanduser("~/.local/share/launcher")
OUT = os.path.join(OUT_DIR, "places.tsv")
LATIN = re.compile(r"^[\x20-\x7eÀ-ɏḀ-ỿ'’.\-]+$")


def norm(text):
    """The launcher's place key: lower, no accents, punctuation -> spaces."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def fetch(name):
    with urllib.request.urlopen(BASE + name, timeout=120) as answer:
        return answer.read()


def main():
    print("downloading GeoNames ...", file=sys.stderr)
    with zipfile.ZipFile(io.BytesIO(fetch("cities5000.zip"))) as z:
        cities = z.read("cities5000.txt").decode("utf-8")
    states = {}
    for line in fetch("admin1CodesASCII.txt").decode("utf-8").splitlines():
        code, name, *_ = line.split("\t")
        states[code] = name
    countries = {}
    for line in fetch("countryInfo.txt").decode("utf-8").splitlines():
        if line and not line.startswith("#"):
            cols = line.split("\t")
            countries[cols[0]] = cols[4]

    rows = []
    for line in cities.splitlines():
        c = line.split("\t")
        name, ascii_name, alternates = c[1], c[2], c[3]
        keys = {norm(name), norm(ascii_name)}
        for alt in alternates.split(","):
            alt = alt.strip()
            if len(alt) > 3 and len(alt) <= 40 and LATIN.match(alt):
                keys.add(norm(alt))
        keys.discard("")
        state = states.get(f"{c[8]}.{c[10]}", "")
        rows.append("|".join(sorted(keys)) + "\t" + "\t".join(
            (name, state, countries.get(c[8], c[8]), c[14], c[4], c[5], c[17])))
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as handle:
        handle.write("\n".join(rows) + "\n")
    os.replace(tmp, OUT)
    print(f"{OUT}: {len(rows)} places, {os.path.getsize(OUT) / 1e6:.1f} MB")

    print("downloading OurAirports ...", file=sys.stderr)
    with urllib.request.urlopen(AIRPORTS_URL, timeout=120) as answer:
        text = answer.read().decode("utf-8")
    airports = []
    for a in csv.DictReader(io.StringIO(text)):
        rank = AIRPORT_RANK.get(a["type"], 0)
        code = a["iata_code"].strip().upper()
        if not code or len(code) != 3 or not rank:
            continue
        if rank == 1 and a["scheduled_service"] != "yes":
            continue
        city = a["municipality"].strip()
        # "Paris (Roissy-en-France, Val-d'Oise)" -> keys "paris roissy en
        # france val d oise" and "paris": the city before the parenthesis.
        keys = {norm(city), norm(city.split("(")[0]), norm(city.split(",")[0])}
        keys.discard("")
        airports.append("\t".join((code, a["name"], city, countries.get(a["iso_country"], a["iso_country"]),
                                   str(rank * 2 + (a["scheduled_service"] == "yes")), a["latitude_deg"], a["longitude_deg"], "|".join(sorted(keys)))))
    out = os.path.join(OUT_DIR, "airports.tsv")
    with open(out + ".tmp", "w") as handle:
        handle.write("\n".join(airports) + "\n")
    os.replace(out + ".tmp", out)
    print(f"{out}: {len(airports)} airports")

    with open(os.path.join(OUT_DIR, "README"), "w") as handle:
        handle.write("places.tsv and airports.tsv: the launcher's place and airport indexes\n"
                     "(~/.config/hypr/scripts/launcher.py), built by\n"
                     "~/.config/hypr/scripts/make-places.py. Rebuild: make-places.py\n\n"
                     "places.tsv: GeoNames (https://www.geonames.org/: cities5000, admin1 and\n"
                     "country names), licensed CC BY 4.0.\n"
                     "airports.tsv: OurAirports (https://ourairports.com/data/), public domain.\n")


if __name__ == "__main__":
    main()
