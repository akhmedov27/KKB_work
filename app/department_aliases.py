"""Search aliases only: original department values are never rewritten."""
from functools import lru_cache
import json
from pathlib import Path
import re


def key(value):
    return re.sub(r'[^а-яa-z0-9]', '', value.casefold().replace('ё', 'е'))


@lru_cache(maxsize=1)
def reference():
    entries = json.loads((Path(__file__).parent / 'reference' / 'department_aliases.json').read_text(encoding='utf-8'))
    aliases = {}
    for entry in entries:
        for alias in entry['aliases']:
            normalized = key(alias)
            if normalized in aliases and aliases[normalized] != entry['name']:
                raise ValueError('Неоднозначный псевдоним в справочнике отделений')
            aliases[normalized] = entry['name']
    return entries, aliases


def resolve(value):
    value = value.strip()
    return reference()[1].get(key(value), value)


def selected_departments(filters):
    values = [*filters.departments, *([filters.department] if filters.department.strip() else [])]
    result, seen = [], set()
    for value in values:
        full = resolve(value)
        if full and full.casefold() not in seen:
            result.append(full)
            seen.add(full.casefold())
    return result


def suggestions(actual_names, query, limit=30):
    entries, aliases = reference()
    actual = {name.casefold(): name for name in actual_names if name}
    candidates = {name: {'value': name, 'label': name, 'present': True} for name in actual.values()}
    for entry in entries:
        if entry['name'].casefold() not in actual:
            candidates.setdefault(entry['name'], {'value': entry['name'], 'label': entry['name'], 'present': False})
    if not query.strip():
        return sorted(candidates.values(), key=lambda item: (not item['present'], item['label'].casefold()))[:limit]
    normalized = key(query)
    exact = aliases.get(normalized) if normalized else None
    matching_names = {entry['name'].casefold() for entry in entries if exact == entry['name'] or
                      (not exact and any(key(alias).startswith(normalized) for alias in entry['aliases']) and normalized)}
    results = [item for item in candidates.values() if item['label'].casefold() in matching_names or
               (not exact and (query.casefold().strip() in item['label'].casefold() or
                              (normalized and normalized in key(item['label']))))]
    if query.strip().casefold() in {'не указано', '__empty__'} and '' in actual_names:
        results.insert(0, {'value': '__empty__', 'label': 'Не указано', 'present': True})
    return sorted(results, key=lambda item: (not item['present'], item['label'].casefold()))[:limit]
