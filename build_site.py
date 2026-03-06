from __future__ import annotations

from pathlib import Path
import html
import re
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

BASE = Path(__file__).resolve().parent
DATA_FILE = BASE / "site.yaml"
TEMPLATE_FILE = "template.html.j2"
OUTPUT_FILE = BASE / "generated_index.html"

PERSON_REF_RE = re.compile(r"\[\[([a-z0-9][a-z0-9-]*)\]\]")
YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def first_nonempty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        return value
    return None


def resolve_person(value: Any, people: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, str):
        if value in people:
            p = as_dict(people[value])
            return {
                "id": value,
                "name": p.get("name", value),
                "url": p.get("url"),
            }
        return {"id": None, "name": value, "url": None}

    if isinstance(value, dict):
        person_id = value.get("id")
        base = as_dict(people.get(person_id)) if person_id else {}
        return {
            "id": person_id,
            "name": value.get("name", base.get("name", person_id or "")),
            "url": value.get("url", base.get("url")),
        }

    return {"id": None, "name": str(value), "url": None}


def resolve_people_list(items: Any, people: dict[str, Any]) -> list[dict[str, Any]]:
    return [resolve_person(x, people) for x in as_list(items)]


def render_inline_people(text: str | None, people: dict[str, Any]) -> str:
    if not text:
        return ""

    out: list[str] = []
    last = 0
    for match in PERSON_REF_RE.finditer(text):
        start, end = match.span()
        key = match.group(1)
        out.append(html.escape(text[last:start]))
        if key in people:
            person = as_dict(people[key])
            name = html.escape(str(person.get("name", key)))
            url = person.get("url")
            if url:
                out.append(f'<a href="{html.escape(str(url), quote=True)}">{name}</a>')
            else:
                out.append(name)
        else:
            out.append(html.escape(match.group(0)))
        last = end
    out.append(html.escape(text[last:]))
    return "".join(out)


def normalize_links(*sources: Any) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for source in sources:
        for link in as_list(source):
            if not isinstance(link, dict):
                continue
            label = str(link.get("label", "Link")).strip() or "Link"
            url = str(link.get("url", "")).strip()
            if url:
                normalized.append({"label": label, "url": url})
    return normalized


def sort_year_keys_desc(mapping: dict[str, Any]) -> list[str]:
    def key_fn(y: str):
        try:
            return (0, int(y))
        except ValueError:
            return (1, y)

    return sorted(mapping.keys(), key=key_fn, reverse=True)


def extract_year(*values: Any) -> str | None:
    for value in values:
        if not value:
            continue
        m = YEAR_RE.search(str(value))
        if m:
            return m.group(0)
    return None


def build_owner(data: dict[str, Any]) -> dict[str, Any]:
    site = as_dict(data.get("site"))
    profile = as_dict(data.get("profile"))
    group = as_dict(profile.get("group"))
    contact = as_dict(data.get("contact"))
    return {
        "name": first_nonempty(profile.get("name"), site.get("title"), "Your Name"),
        "position": first_nonempty(profile.get("role"), profile.get("position")),
        "affiliation": profile.get("affiliation"),
        "photo": first_nonempty(site.get("photo"), profile.get("photo")),
        "email": first_nonempty(contact.get("primary_email"), contact.get("email")),
        "group": {
            "name": group.get("name"),
            "url": group.get("url"),
        },
    }


def normalize_publications(publications: dict[str, Any], people: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "thesis": None,
        "conferences": {},
        "workshops": {},
        "preprints": [],
    }

    thesis = as_dict(publications.get("thesis"))
    if thesis:
        out["thesis"] = {
            "title": thesis.get("title"),
            "description": thesis.get("description"),
            "authors": resolve_people_list(thesis.get("authors", ["antonio-cruciani"]), people),
            "links": normalize_links(
                thesis.get("links"),
                {"label": "PDF", "url": thesis.get("pdf")},
                {"label": "Slides", "url": thesis.get("slides")},
            ),
        }

    conferences = as_dict(publications.get("conferences"))
    for year, entries in conferences.items():
        y = str(year)
        out["conferences"][y] = []
        for entry in as_list(entries):
            if not isinstance(entry, dict):
                continue
            out["conferences"][y].append(
                {
                    "title": entry.get("title"),
                    "venue": entry.get("venue"),
                    "status": entry.get("status"),
                    "authors": resolve_people_list(entry.get("authors", []), people),
                    "note": entry.get("note"),
                    "links": normalize_links(entry.get("links")),
                }
            )

    workshops = as_list(publications.get("workshops_and_posters"))
    for entry in workshops:
        if not isinstance(entry, dict):
            continue
        year = extract_year(entry.get("year"), entry.get("event")) or "Other"
        out["workshops"].setdefault(year, []).append(
            {
                "title": entry.get("title"),
                "venue": entry.get("event"),
                "authors": resolve_people_list(entry.get("authors", []), people),
                "links": normalize_links(entry.get("links")),
            }
        )

    for entry in as_list(publications.get("preprints")):
        if not isinstance(entry, dict):
            continue
        out["preprints"].append(
            {
                "title": entry.get("title"),
                "authors": resolve_people_list(entry.get("authors", []), people),
                "note": entry.get("note"),
                "links": normalize_links(entry.get("links")),
            }
        )

    return out


def normalize_talks(talks: Any) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(talks, dict):
        return out
    for year, entries in talks.items():
        y = str(year)
        out[y] = []
        for entry in as_list(entries):
            if not isinstance(entry, dict):
                continue
            links = []
            if entry.get("slides_url"):
                links.append({"label": "Slides", "url": entry.get("slides_url")})
            if entry.get("event_url"):
                links.append({"label": "Event", "url": entry.get("event_url")})
            links.extend(normalize_links(entry.get("links")))
            out[y].append(
                {
                    "title": entry.get("title"),
                    "event": entry.get("event"),
                    "location": entry.get("location"),
                    "date": entry.get("date"),
                    "description": entry.get("description"),
                    "coauthors": [],
                    "links": links,
                }
            )
    return out


def normalize_projects(projects: Any, people: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    p = as_dict(projects)
    out: dict[str, list[dict[str, Any]]] = {"ongoing": [], "past": []}
    for section in ["ongoing", "past"]:
        for entry in as_list(p.get(section)):
            if not isinstance(entry, dict):
                continue
            out[section].append(
                {
                    "title": entry.get("title"),
                    "description": entry.get("description"),
                    "collaborators": resolve_people_list(entry.get("collaborators", []), people),
                    "links": normalize_links(entry.get("links")),
                }
            )
    return out


def normalize_cv(cv: Any, people: dict[str, Any]) -> dict[str, Any]:
    c = as_dict(cv)
    out = {"full_cv_url": c.get("full_cv_url"), "entries": []}
    for entry in as_list(c.get("education")):
        if not isinstance(entry, dict):
            continue
        description_parts: list[str] = []
        if entry.get("location"):
            description_parts.append(f"Location: {entry['location']}")
        if entry.get("thesis"):
            description_parts.append(f"Thesis: {entry['thesis']}")
        out["entries"].append(
            {
                "title": entry.get("degree"),
                "institution": entry.get("institution"),
                "period": entry.get("date"),
                "description": " · ".join(description_parts),
                "supervisor_label": "Supervised by",
                "supervisors": resolve_people_list(entry.get("supervisors", []), people),
                "links": normalize_links(
                    entry.get("links"),
                    {"label": "Institution", "url": entry.get("institution_url")},
                ),
            }
        )
    return out


def normalize_code(code: Any, people: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for entry in as_list(code):
        if not isinstance(entry, dict):
            continue
        out.append(
            {
                "title": entry.get("title"),
                "description": entry.get("description"),
                "collaborators": resolve_people_list(entry.get("collaborators", []), people),
                "links": normalize_links(
                    {"label": "Code", "url": entry.get("code_url")},
                    entry.get("extra_links"),
                    entry.get("links"),
                ),
            }
        )
    return out


def normalize_teaching(teaching: Any) -> list[dict[str, Any]]:
    out = []
    for entry in as_list(teaching):
        if not isinstance(entry, dict):
            continue
        items = [str(x) for x in as_list(entry.get("items")) if str(x).strip()]
        title = items[0] if items else entry.get("title")
        description = "<br>".join(html.escape(x) for x in items[1:]) if len(items) > 1 else entry.get("description")
        out.append(
            {
                "title": title,
                "period": entry.get("period"),
                "description": description,
                "links": normalize_links(entry.get("links")),
            }
        )
    return out


def normalize_contact(contact: Any) -> list[dict[str, Any]]:
    c = as_dict(contact)
    out: list[dict[str, Any]] = []
    if c.get("primary_email"):
        out.append({"label": "Primary email", "value": c["primary_email"], "url": None})
    if c.get("secondary_email"):
        out.append({"label": "Secondary email", "value": c["secondary_email"], "url": None})
    if c.get("pgp_url"):
        out.append({"label": "PGP key", "value": c["pgp_url"], "url": c["pgp_url"]})
    address_lines = [str(x) for x in as_list(c.get("address_lines")) if str(x).strip()]
    if address_lines:
        out.append({"label": "Address", "value": "<br>".join(html.escape(x) for x in address_lines), "url": None, "is_html": True})
    for link in normalize_links(c.get("links")):
        out.append({"label": link["label"], "value": link["label"], "url": link["url"]})
    return out


def normalize_navigation(site: dict[str, Any]) -> list[dict[str, str]]:
    nav = [x for x in as_list(site.get("navigation")) if isinstance(x, dict)]
    if nav:
        return [
            {"id": str(item.get("id", "")).strip(), "label": str(item.get("label", item.get("id", ""))).strip()}
            for item in nav
            if str(item.get("id", "")).strip()
        ]
    return [
        {"id": "about", "label": "Bio"},
        {"id": "publications", "label": "Publications"},
        {"id": "talks", "label": "Talks"},
        {"id": "projects", "label": "Projects"},
        {"id": "cv", "label": "CV"},
        {"id": "code", "label": "Code"},
        {"id": "teaching", "label": "Teaching"},
        {"id": "contact", "label": "Contacts"},
    ]


def normalize_data(data: dict[str, Any]) -> dict[str, Any]:
    people = as_dict(data.get("people"))
    site = as_dict(data.get("site"))
    profile = as_dict(data.get("profile"))

    normalized: dict[str, Any] = {
        "site": site,
        "owner": build_owner(data),
        "bio": {
            "paragraphs": [str(x) for x in as_list(profile.get("bio")) if str(x).strip()],
            "interests": [str(x) for x in as_list(profile.get("research_focus")) if str(x).strip()],
        },
        "news": [x for x in as_list(profile.get("news")) if isinstance(x, dict)],
        "projects": normalize_projects(data.get("projects"), people),
        "publications": normalize_publications(as_dict(data.get("publications")), people),
        "cv": normalize_cv(data.get("cv"), people),
        "talks": normalize_talks(data.get("talks")),
        "code": normalize_code(data.get("code"), people),
        "teaching": normalize_teaching(data.get("teaching")),
        "contacts": normalize_contact(data.get("contact")),
        "navigation": normalize_navigation(site),
    }

    normalized["_years"] = {
        "conferences": sort_year_keys_desc(normalized["publications"]["conferences"]),
        "workshops": sort_year_keys_desc(normalized["publications"]["workshops"]),
        "talks": sort_year_keys_desc(normalized["talks"]),
    }
    return normalized


with DATA_FILE.open("r", encoding="utf-8") as f:
    raw_data = yaml.safe_load(f) or {}

people = as_dict(raw_data.get("people"))
data = normalize_data(raw_data)

env = Environment(
    loader=FileSystemLoader(str(BASE)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

env.filters["render_people_text"] = lambda text: render_inline_people(text, people)

template = env.get_template(TEMPLATE_FILE)
html_output = template.render(**data)
OUTPUT_FILE.write_text(html_output, encoding="utf-8")

print(f"Generated {OUTPUT_FILE.name} from {DATA_FILE.name}")
