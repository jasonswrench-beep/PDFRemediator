"""Local RFC 5646 well-formedness checks, without registry lookup or inference.

This checks syntax, not whether a tag is registered or describes the content.
The original spelling is retained; no language is inferred or canonicalized.
"""
import re

_ALPHA = re.compile(r'^[A-Za-z]+$')
_ALNUM = re.compile(r'^[A-Za-z0-9]+$')
_GRANDFATHERED = frozenset(x.lower() for x in (
    'art-lojban','cel-gaulish','en-GB-oed','i-ami','i-bnn','i-default',
    'i-enochian','i-hak','i-klingon','i-lux','i-mingo','i-navajo','i-pwn',
    'i-tao','i-tay','i-tsu','no-bok','no-nyn','sgn-BE-FR','sgn-BE-NL',
    'sgn-CH-DE','zh-guoyu','zh-hakka','zh-min','zh-min-nan','zh-xiang'))


def validate_language_tag(value):
    """Return an unchanged well-formed tag, or raise ValueError.

    RFC 5646 language/script/region/variant/extension/private-use and the finite
    grandfathered set are supported. Duplicate variants/singletons are refused.
    A bounded 255-character input prevents unbounded property values.
    """
    if (not isinstance(value, str) or not 1 <= len(value) <= 255 or
            value != value.strip() or not value.isascii()):
        raise ValueError('Use a language tag such as en-US, fr, or zh-Hant; tags must be ASCII and at most 255 characters')
    if value.lower() in _GRANDFATHERED:
        return value
    parts=value.split('-')
    if any(not 1 <= len(p) <= 8 or not _ALNUM.fullmatch(p) for p in parts):
        raise ValueError('Language subtags must contain 1–8 ASCII letters or digits, separated by single hyphens')
    if parts[0].lower()=='x':
        if len(parts)<2:raise ValueError('Private-use language tags require a subtag after x-')
        return value
    primary=parts[0]
    if not 2 <= len(primary) <= 8 or not _ALPHA.fullmatch(primary):
        raise ValueError('A language tag requires a 2–8 letter primary language subtag')
    i=1
    if len(primary)<=3:
        count=0
        while i<len(parts) and len(parts[i])==3 and _ALPHA.fullmatch(parts[i]) and count<3:
            i+=1;count+=1
    if i<len(parts) and len(parts[i])==4 and _ALPHA.fullmatch(parts[i]):i+=1
    if i<len(parts) and ((len(parts[i])==2 and _ALPHA.fullmatch(parts[i])) or
            (len(parts[i])==3 and parts[i].isdigit())):i+=1
    variants=set()
    while i<len(parts) and (5<=len(parts[i])<=8 or (len(parts[i])==4 and parts[i][0].isdigit())):
        token=parts[i].lower()
        if token in variants:raise ValueError('A language variant cannot be repeated')
        variants.add(token);i+=1
    extensions=set()
    while i<len(parts) and len(parts[i])==1 and parts[i].lower()!='x':
        token=parts[i].lower()
        if token in extensions:raise ValueError('A language extension singleton cannot be repeated')
        extensions.add(token);i+=1;start=i
        while i<len(parts) and 2<=len(parts[i])<=8:i+=1
        if i==start:raise ValueError('A language extension requires a 2–8 character subtag')
    if i<len(parts) and parts[i].lower()=='x':
        i+=1
        if i==len(parts):raise ValueError('Private-use language tags require a subtag after x-')
        i=len(parts)
    if i!=len(parts):raise ValueError('Language subtags are malformed or out of order')
    return value


def is_language_tag(value):
    try:
        validate_language_tag(value)
        return True
    except ValueError:
        return False
