"""Vietnamese integer money/phone extraction without reference-text access."""
import re
import unicodedata
from datetime import date, timedelta

DIGITS = 'không một hai ba bốn năm sáu bảy tám chín'.split()
VERSION = 'vi-numbers-v3'
ALIASES = {'mốt': 'một', 'lăm': 'năm', 'tư': 'bốn', 'ngàn': 'nghìn', 'lẻ': 'linh', 'k':'nghìn'}
NUMBER_WORDS = set(DIGITS) | set(ALIASES) | {'mười', 'mươi', 'trăm', 'linh', 'nghìn', 'triệu', 'tỷ'}


def integer_words(text, colloquial=False):
    """Parse an explicitly spoken integer; reject adjacent digits without a scale."""
    words = [ALIASES.get(t, t) for t in text.split()]
    total, group, last_digit, digit = 0, 0, False, 0
    for t in words:
        if t in DIGITS:
            if last_digit:
                # C.1 example: 'hai trăm bốn chín k' means 249k.
                if group>=100 and digit>0 and len(words)>=4 and words[-1]=='nghìn':
                    group += digit*9
                else:
                    raise ValueError('Adjacent digits are not a money amount')
            group += DIGITS.index(t)
            digit = DIGITS.index(t)
            last_digit = True
        elif t == 'trăm':
            group *= 100
            last_digit = False
        elif t in ('mươi', 'mười'):
            group = group + digit * 9 if t == 'mươi' else group + 10
            last_digit = False
        elif t == 'linh':
            last_digit = False
        elif t in ('nghìn', 'triệu', 'tỷ'):
            scale = {'nghìn': 1000, 'triệu': 1000000, 'tỷ': 1000000000}[t]
            total += group * scale
            group, last_digit = 0, False
        else:
            raise ValueError('Unsupported integer word')
    # Explicit colloquial VND convention after 'triệu': 4 triệu 890 -> 4,890,000.
    # Other omitted-unit forms remain unsupported.
    if colloquial and 'triệu' in words and words[-1] not in ('nghìn','triệu','tỷ') and 100<=group<1000:
        group *= 1000
    return total + group


def spoken(n):
    if n < 10:
        return DIGITS[n]
    for scale, unit in ((1000000000, 'tỷ'), (1000000, 'triệu'), (1000, 'nghìn')):
        if n >= scale:
            q, r = divmod(n, scale)
            return spoken(q) + ' ' + unit + (' ' + spoken(r) if r else '')
    h, r = divmod(n, 100)
    result = [DIGITS[h], 'trăm'] if h else []
    if h and 0 < r < 10:
        result.append('linh')
    tens, ones = divmod(r, 10)
    if tens:
        result.extend(['mười'] if tens == 1 else [DIGITS[tens], 'mươi'])
    if ones:
        result.append('lăm' if tens and ones == 5 else 'mốt' if tens > 1 and ones == 1 else DIGITS[ones])
    return ' '.join(result)


def normalize(text):
    text = unicodedata.normalize('NFC', text.lower())
    text = re.sub(r'(\d)\s*k\b',r'\1 nghìn',text)
    # Join grouped telephone digits and thousand separators before punctuation removal.
    text = re.sub(r'\b0(?:[ .-]?\d){9}\b', lambda m: re.sub(r'\D', '', m[0]), text)
    text = re.sub(r'\b\d{1,3}(?:[.,]\d{3})+\b', lambda m: re.sub(r'\D', '', m[0]), text)
    # WER/CER lexical view only; callback dates are parsed separately with declared context.
    text = re.sub(r'\d+', lambda m: ' '.join(DIGITS[int(x)] for x in m[0])
                  if m[0].startswith('0') else spoken(int(m[0])), text)
    text = re.sub(r'[^\w\s]', ' ', text)
    return ' '.join(text.split())


def callback_date(text, call_date=None):
    """Team supplemental date ITN; never infer a date without callback context."""
    text = unicodedata.normalize('NFC', text.lower())
    if not re.search(r'gọi lại|hẹn gọi|liên hệ lại', text):
        return {}, []
    found = []
    try:
        base = date.fromisoformat(call_date) if call_date else None
        for offset, pattern in ((2, r'ngày kia'), (1, r'ngày mai|chiều mai|sáng mai|tối mai|\bmai\b')):
            if re.search(pattern, text):
                if not base:
                    return {}, [{'kind': 'DATE_CONTEXT_MISSING'}]
                found.append((base + timedelta(days=offset)).isoformat())
        for m in re.finditer(r'\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?\b', text):
            year = int(m[3]) if m[3] else base.year if base else None
            if year is None:
                return {}, [{'kind': 'DATE_CONTEXT_MISSING'}]
            found.append(date(year, int(m[2]), int(m[1])).isoformat())
        for m in re.finditer(r'ngày ([\w\s]+?) tháng ([\w\s]+?)(?: năm ([\w\s]+?))?(?=[.,!?]|$)', text):
            def number(value):
                value = value.strip()
                return int(value) if value.isdigit() else integer_words(value)
            year = number(m[3]) if m[3] else base.year if base else None
            if year is None:
                return {}, [{'kind': 'DATE_CONTEXT_MISSING'}]
            found.append(date(year, number(m[2]), number(m[1])).isoformat())
    except (ValueError, TypeError):
        return {}, [{'kind': 'INVALID_CALLBACK_DATE'}]
    if len(set(found)) == 1:
        return {'callback_date': found[0]}, []
    return {}, [{'kind': 'AMBIGUOUS_CALLBACK_DATE' if found else 'UNSUPPORTED_CALLBACK_DATE'}]


def extract(text):
    """Return entities and diagnostics. Do not fill missing phone digits.

    Explicit last price/budget mention wins. Ambiguous ranges remain unextracted.
    SKU/area are unsupported; callback date is a separate supplemental extraction.
    """
    norm = normalize(text)
    result, diagnostics = {}, []
    tokens = norm.split()
    i = 0
    while i < len(tokens):
        if tokens[i] not in DIGITS:
            i += 1
            continue
        end = i
        while end < len(tokens) and tokens[end] in DIGITS:
            end += 1
        seq = tokens[i:end]
        if seq[0] == 'không' and len(seq) >= 6:
            phone = ''.join(str(DIGITS.index(t)) for t in seq)
            if len(phone) == 10:
                result['phone'] = phone
            else:
                result.pop('phone', None)
                diagnostics.append({'kind': 'INVALID_PHONE_LENGTH', 'candidate': phone, 'digits': len(phone)})
        i = end
    source = unicodedata.normalize('NFC', text.lower())
    for m in re.finditer(r'\b(giá|ngân sách)\s+(?:là\s+|khoảng\s+|tầm\s+)?', source):
        fragment = source[m.end():]
        literal = re.match(r'(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(?:đồng|vnd)\b', fragment)
        # Preserve exact numeric money rather than reinterpreting it as colloquial speech.
        if literal and not re.match(r'\s*(?:đến|tới)', fragment[literal.end():]):
            amount = int(re.sub(r'\D', '', literal[1]))
            if amount > 0:
                result['price_vnd' if m[1] == 'giá' else 'budget_vnd'] = amount
            continue
        fragment = normalize(fragment)
        words = []
        for token in fragment.split():
            if token not in NUMBER_WORDS:
                break
            words.append(token)
        tail = fragment.split()[len(words):]
        if not words:
            continue  # e.g. 'đây là giá minh họa' is not another price claim.
        if tail and tail[0] in ('đến', 'tới', 'phẩy'):
            result.pop('price_vnd' if m[1] == 'giá' else 'budget_vnd', None)
            diagnostics.append({'kind': 'AMBIGUOUS_MONEY', 'context': norm[m.start():m.start()+80]})
            continue
        try:
            amount = integer_words(' '.join(words), colloquial=True)
            if amount <= 0 or not (set(words) & {'triệu', 'nghìn', 'ngàn', 'tỷ', 'k'} or (tail and tail[0] in ('đồng', 'vnd'))):
                continue
            result['price_vnd' if m[1] == 'giá' else 'budget_vnd'] = amount
        except ValueError:
            diagnostics.append({'kind': 'UNSUPPORTED_MONEY', 'text': ' '.join(words)})
    return result, diagnostics


def entities(text):
    return extract(text)[0]
