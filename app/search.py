"""Literal Unicode search and bounded, escaped-by-template source excerpts."""
import json


def casefold(value):
    return (value or '').casefold()


def literal_position(text, query):
    needle = casefold(query)
    if not needle:
        return -1
    folded = casefold(text)
    position = folded.find(needle)
    if position < 0 or len(folded) == len(text):
        return position
    # Unicode folding may expand characters (e.g. ß); return an original offset.
    offset = 0
    for index, char in enumerate(text):
        offset += len(char.casefold())
        if offset > position:
            return index
    return -1


def source_maps(raw, text_length):
    try:
        data = json.loads(raw or '[]')
        previous_end = 0
        for item in data:
            start, end = item['start'], item['end']
            if not (isinstance(start, int) and isinstance(end, int) and previous_end <= start <= end <= text_length):
                return []
            if not isinstance(item['label'], str):
                return []
            previous_end = end
        return data
    except (ValueError, TypeError, KeyError):
        return []


def excerpt(text, query, raw_sources):
    text = text or ''
    position = literal_position(text, query)
    if position < 0:
        return json.dumps({'text': '', 'anchor': 'document-metadata', 'location': None})
    start, end = max(0, position - 100), min(len(text), position + max(len(query), 80) + 160)
    maps = source_maps(raw_sources, len(text))
    source = next(((index, item) for index, item in enumerate(maps) if item['start'] <= position < item['end']), None)
    if source:
        start, end = max(start, source[1]['start']), min(end, source[1]['end'])
    return json.dumps({'text': ('…' if start else '') + text[start:end] + ('…' if end < len(text) else ''),
                       'anchor': f'source-{source[0]}' if source else 'document-text',
                       'location': source[1]['label'] if source else None}, ensure_ascii=False)


def text_parts(text, raw_sources):
    maps = source_maps(raw_sources, len(text))
    if not maps:
        return [{'anchor': '', 'text': text}]
    parts, offset = [], 0
    for index, item in enumerate(maps):
        if item['start'] > offset:
            parts.append({'anchor': '', 'text': text[offset:item['start']]})
        parts.append({'anchor': f'source-{index}', 'text': text[item['start']:item['end']]})
        offset = item['end']
    if offset < len(text):
        parts.append({'anchor': '', 'text': text[offset:]})
    return parts
