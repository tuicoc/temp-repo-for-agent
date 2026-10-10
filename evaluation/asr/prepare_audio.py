"""Generate explicitly synthetic Vietnamese ASR data; never use BTC test answers."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import wave
import sys
import importlib.util
from datetime import date, timedelta

import av
import edge_tts
import numpy as np

ROOT = Path(__file__).resolve().parent
RATE = 16000
VOICES = {'A': 'vi-VN-HoaiMyNeural', 'C': 'vi-VN-NamMinhNeural'}
DIGITS = 'không một hai ba bốn năm sáu bảy tám chín'.split()
PHONE_VARIANTS = {5: '0901385724', 6: '0917462853', 8: '0935827164', 14: '0964718253',
                  15: '0972358641', 16: '0986143725', 18: '0327486159', 19: '0839261475'}


def phone_variant_scripts():
    """Diagnostic variants of eight known failures; preserve the original corpus."""
    import copy
    original = json.loads((ROOT/'datasets/synthetic-v1/eval/ground_truth.json').read_text(encoding='utf-8'))
    data = []
    for source in original['dialogues']:
        index = int(source['id'].split('-')[-1])
        if index not in PHONE_VARIANTS:
            continue
        d = copy.deepcopy(source)
        phone = PHONE_VARIANTS[index]
        grouped = ', '.join(' '.join(DIGITS[int(x)] for x in phone[a:b]) for a,b in ((0,3),(3,6),(6,10)))
        for turn in d['turns']:
            if 'điện thoại' in turn['text']:
                turn['text'] = 'Số điện thoại liên hệ của tôi là ' + grouped + '.'
        d.update(id=f'TEAM-PHONE-V1-{index:02d}', split='eval', source_id=source['id'],
                 experiment='diagnostic_selected_failures_varied_digits_and_334_grouping',
                 review_status='pending_human_listening', original_phone=source['entities']['phone'])
        d['entities']['phone'] = phone
        d['full_text'] = ' '.join(t['text'] for t in d['turns'])
        data.append(d)
    return data


def catalog_scripts(total=24, dev_count=4):
    """24 team calls; 4 dev + 20 eval. Prices use pinned BTC quote logic."""
    from text_processing import spoken
    sys.dont_write_bytecode = True
    btc = ROOT.parent/'evaluation-contracts/sources/btc'
    spec = importlib.util.spec_from_file_location('btc_quote', btc/'eval/mock_tools.py')
    mock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mock)
    catalog = json.loads((btc/'catalog/products.json').read_text(encoding='utf-8'))
    skus = ['SKU-AP-X','SKU-SN-RUN1','SKU-MB-STR1']
    for n in range(1,total+1):
        split = 'dev' if n<=dev_count else 'eval'
        customer = (n-1)//2 + 1
        call = (n-1)%2+1
        product = next(p for p in catalog['products'] if p['sku']==skus[(customer-1)%3])
        phone = '090' + f'{(1234567+customer*7919)%10000000:07d}'
        on = (date(2026,10,15)+timedelta(days=call-1)).isoformat()
        quote = mock.pricing_get_quote(product['sku'], on=on, customer_phone=phone)
        price = quote['final_price_vnd']
        spoken_phone = ', '.join(' '.join(DIGITS[int(t)] for t in phone[a:b]) for a,b in ((0,3),(3,6),(6,10)))
        intent = customer%5
        requests = [
            ('Tôi muốn hỏi thêm nhưng chưa mua ngay.', 'Dạ mình có thể cân nhắc thêm, em chưa tạo đơn hàng.'),
            ('Để tôi hỏi người nhà trước khi quyết định.', 'Dạ mình cứ trao đổi thêm với người nhà rồi liên hệ lại ạ.'),
            ('Tôi thấy nơi khác báo giá khác, cho tôi xem giá của cửa hàng.', 'Dạ em cung cấp giá của cửa hàng để mình tham khảo.'),
            ('Tôi muốn gặp nhân viên để hỏi về đổi trả sản phẩm đã mua.', 'Dạ em sẽ chuyển yêu cầu cho nhân viên, chưa xác nhận đủ điều kiện đổi trả.'),
            ('Tôi đã gọi rồi, lần này mong được hỗ trợ rõ ràng hơn.', 'Dạ em ghi nhận và sẽ chuyển thông tin mình cần hỗ trợ cho nhân viên.')]
        question,answer = requests[intent]
        callback = (date.fromisoformat(on) + timedelta(days=1)).isoformat()
        turns = [('A','Xin chào, cửa hàng xin nghe. Em có thể hỗ trợ mình như thế nào ạ?'),
                 ('C',f'Tôi {"quay lại hỏi" if call==2 else "muốn tìm hiểu"} {product["name"]}.'),
                 ('A',f'Dạ sản phẩm {product["name"]} có giá {spoken(price)} đồng tại ngày gọi này.'),
                 ('C',question), ('A',answer),
                 ('C',f'Ngân sách của tôi là {spoken(price+500000)} đồng.'),
                 ('C','Số điện thoại liên hệ của tôi là '+spoken_phone+'.'),
                 ('C','Mình hẹn gọi lại vào ngày mai nhé.'),
                 ('A','Dạ em đã ghi nhận. Cảm ơn mình đã liên hệ cửa hàng.')]
        yield {'id':f'TEAM-V3-{split.upper()}-{n:02d}', 'split':split,
               'customer_id':f'SYN-C{customer:02d}', 'call_index':call,'call_date':on,
               'product_sku':product['sku'], 'industry':product['category'].split('/')[0],
               'noisy': (n==4 or (n>4 and n%5==4)), 'source':'synthetic_edge_tts',
               'region':'unverified', 'review_status':'pending_human_listening',
               'turns':[{'speaker':s,'text':t} for s,t in turns],
               'full_text':' '.join(t for _,t in turns),
               'entities':{'price_vnd':price, 'budget_vnd':price+500000, 'phone':phone},
               'supplemental_entities': {'callback_date': callback},
               'quote_evidence':{'source':'BTC pricing_get_quote', 'on':on,'sku':product['sku'],
                                 'applied_promos':quote['applied_promos'], 'final_price_vnd':price}}


def voicemaker_scripts():
    """Proposed corpus: text only, pending voice selection and listening review."""
    data = list(catalog_scripts(total=26, dev_count=6))
    for index, d in enumerate(data, 1):
        customer = (index-1)//2+1
        region = ('north', 'central', 'south')[customer-1] if customer <= 3 else (
            'north' if customer <= 7 else 'central' if customer <= 10 else 'south')
        d.update(id=f'VM-V1-{d["split"].upper()}-{index:02d}', source='planned_fpt_voicemaker',
                 planned_customer_region=region, region='unverified',
                 voice_plan={'agent_voice_id': None, 'customer_voice_id': None,
                             'agent_region': 'north', 'customer_region': region},
                 noisy=index in (6, 10, 15, 20, 25),
                 noise_plan={'kind': 'telephone_band_and_white_noise', 'snr_db': 20,
                             'band_hz': [300, 3400], 'seed': index} if index in (6, 10, 15, 20, 25) else None)
        on = date.fromisoformat(d['call_date'])
        offset = 2 if customer%3 == 2 else 1
        target = on + timedelta(days=offset)
        callback_text = ('Mình hẹn gọi lại vào ngày mai nhé.' if customer%3 == 0 else
                         'Mình hẹn gọi lại vào ngày kia nhé.' if customer%3 == 2 else
                         f'Mình hẹn gọi lại ngày {target.day} tháng {target.month} năm {target.year}.')
        for turn in d['turns']:
            if 'hẹn gọi lại' in turn['text']:
                turn['text'] = callback_text
        d['supplemental_entities']['callback_date'] = target.isoformat()
        d['full_text'] = ' '.join(t['text'] for t in d['turns'])
    return data


def write_script_book(folder, data):
    text = '# Script Voice Maker v1 — chờ duyệt\n\n'
    text += ('26 hội thoại: 6 dev + 20 eval. Chỉ là script, chưa có audio; vùng miền chưa được xác minh. '
             'SĐT giả lập, không gọi/nhắn tin. Agent A / khách C dùng hai voice khác nhau. '
             'Chỉ gửi từng `turn.text` lên TTS, không gửi GT/metadata. Không đổi script sau khi khóa; '
             'nếu TTS đọc khác, nghe duyệt rồi tạo version mới.\n\n')
    text += '## Danh sách\n\n| ID | Miền khách dự kiến | Nhiễu | SKU | SĐT | Ngày gọi | Hẹn |\n|---|---|---|---|---|---|---|\n'
    for d in data:
        text += f'| {d["id"]} | {d["planned_customer_region"]} | {d["noisy"]} | {d["product_sku"]} | {d["entities"]["phone"]} | {d["call_date"]} | {d["supplemental_entities"]["callback_date"]} |\n'
    for d in data:
        text += f'\n## {d["id"]}\n\nKhách `{d["customer_id"]}`, call {d["call_index"]}; region dự kiến `{d["planned_customer_region"]}`.\n\n'
        text += '\n'.join(f'{i}. **{turn["speaker"]}:** {turn["text"]}' for i, turn in enumerate(d['turns'], 1)) + '\n'
        text += '\nGT tiền/SĐT: `' + json.dumps(d['entities'], ensure_ascii=False) + '`; GT ngày bổ sung: `' + json.dumps(d['supplemental_entities']) + '`.\n'
    (folder/'scripts.md').write_text(text, encoding='utf-8')


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def decode(path):
    resampler = av.AudioResampler(format='s16', layout='mono', rate=RATE)
    frames = []
    with av.open(str(path)) as source:
        for frame in source.decode(audio=0):
            frames.extend(x.to_ndarray().flatten() for x in resampler.resample(frame))
        frames.extend(x.to_ndarray().flatten() for x in resampler.resample(None))
    return np.concatenate(frames).astype(np.float32) / 32768


def scripts():
    needs = [
        'phòng ngủ', 'phòng khách', 'phòng làm việc', 'căn hộ nhỏ',
        'phòng có em bé', 'nhà nuôi mèo', 'nhà gần đường lớn', 'phòng tập',
        'cửa hàng', 'phòng đọc sách', 'nhà có người lớn tuổi', 'phòng trọ',
        'phòng họp', 'phòng học', 'nhà nuôi chó', 'phòng sinh hoạt',
        'phòng có nhiều bụi', 'nhà mới sửa', 'phòng có mùi thức ăn', 'văn phòng',
        'phòng giải trí', 'nhà nghỉ cuối tuần', 'phòng nghỉ', 'phòng làm việc chung',
    ]
    questions = [
        ('Máy có dễ thay màng lọc không?', 'Mình có thể tháo nắp để thay màng lọc theo hướng dẫn đi kèm.'),
        ('Tôi muốn được tư vấn thêm trước khi mua.', 'Dạ em ghi nhận, mình chưa cần đặt hàng ngay ạ.'),
        ('Có thể gọi lại cho tôi vào chiều mai không?', 'Dạ em sẽ ghi nhận yêu cầu gọi lại vào chiều mai.'),
        ('Tôi muốn gặp nhân viên để hỏi kỹ hơn.', 'Dạ em sẽ chuyển yêu cầu tư vấn của mình cho nhân viên.'),
    ]
    for n, need in enumerate(needs, 1):
        split = 'dev' if n <= 4 else 'eval'
        phone = f'090000{n:04d}'  # Fictional fixture; never dial.
        money = 3 + n % 5
        price = DIGITS[money] + ' triệu đồng'
        question, answer = questions[(n - 1) % len(questions)]
        turns = [
            ('A', 'Xin chào, em có thể hỗ trợ mình về máy lọc không khí như thế nào ạ?'),
            ('C', f'Tôi cần một máy lọc không khí cho {need}. Xin tư vấn giúp tôi.'),
            ('A', f'Dạ mẫu máy tham khảo có giá {price}. Đây là giá minh họa trong cuộc gọi thử nghiệm.'),
            ('C', question), ('A', answer),
            ('C', 'Số điện thoại liên hệ của tôi là ' + ' '.join(DIGITS[int(x)] for x in phone) + '.'),
            ('A', 'Dạ em đã ghi nhận thông tin. Cảm ơn mình đã gọi đến cửa hàng.'),
        ]
        yield {'id': f'TEAM-{split.upper()}-{n:02d}', 'split': split,
               'noisy': n % 4 == 0, 'turns': [dict(speaker=s, text=t) for s, t in turns],
               'full_text': ' '.join(t for _, t in turns),
               'entities': {'price_vnd': money * 1000000, 'phone': phone},
               'review_status': 'pending_human_listening', 'source': 'synthetic_edge_tts',
               'region': 'unverified', 'scenario_type': ['product', 'consideration', 'callback', 'handoff'][(n-1) % 4]}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, default=ROOT / 'datasets' / 'synthetic-v1')
    ap.add_argument('--catalog-based', action='store_true', help='Catalog v3: BTC quotes, varied phone digits and callback dates')
    ap.add_argument('--scripts-only', action='store_true', help='Prepare scripts/GT offline without contacting any TTS service')
    ap.add_argument('--phone-variants', action='store_true', help='Eight diagnostic variants; requires a fresh --out')
    ap.add_argument('--voicemaker-scripts', action='store_true', help='Prepare proposed 6 dev + 20 eval scripts only; no API calls')
    ap.add_argument('--input-scripts', type=Path, help='Render an existing script book with the original Edge TTS voices into a new dataset')
    args = ap.parse_args()
    if args.input_scripts and (args.voicemaker_scripts or args.catalog_based or args.phone_variants):
        ap.error('--input-scripts cannot be combined with another dataset mode')
    if args.voicemaker_scripts and (not args.scripts_only or args.catalog_based or args.phone_variants):
        ap.error('--voicemaker-scripts requires --scripts-only and no other dataset mode')
    if args.phone_variants and (args.catalog_based or args.out.resolve() == (ROOT/'datasets/synthetic-v1').resolve()):
        ap.error('--phone-variants needs a separate --out and cannot use --catalog-based')
    data = voicemaker_scripts() if args.voicemaker_scripts else phone_variant_scripts() if args.phone_variants else list(catalog_scripts() if args.catalog_based else scripts())
    if args.input_scripts:
        if args.out.resolve() == args.input_scripts.resolve().parent:
            ap.error('--input-scripts requires a separate output dataset')
        data = json.loads(args.input_scripts.read_text(encoding='utf-8'))
        if not isinstance(data, list) or not data:
            raise ValueError('Input scripts must be a nonempty list')
        ids = set()
        for d in data:
            key = d['id']
            if not isinstance(key, str) or not key or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in key) or key in ids:
                raise ValueError('Invalid or duplicate script ID')
            ids.add(key)
            if d['split'] not in ('dev', 'eval') or not d['turns']:
                raise ValueError('Invalid split or empty turns')
            for turn in d['turns']:
                if turn['speaker'] not in VOICES or not isinstance(turn['text'], str) or not turn['text'].strip():
                    raise ValueError('Invalid speaker or empty text')
            if d['full_text'] != ' '.join(t['text'] for t in d['turns']):
                raise ValueError('Transcript does not match turns')
            d.update(source='synthetic_edge_tts', region='unverified',
                     review_status='pending_human_listening', voices=VOICES)
            d.pop('voice_plan', None)
    script_path = args.out / 'scripts.json'
    if script_path.exists():
        if json.loads(script_path.read_text(encoding='utf-8')) != data:
            raise ValueError('Script changed: choose a new --out dataset version before generating audio')
    else:
        save(script_path, data)
    if args.voicemaker_scripts:
        write_script_book(args.out, data)
    if args.scripts_only:
        for split in ('dev', 'eval'):
            target = args.out/split/'ground_truth.json'
            if not target.exists():
                save(target, {'description': 'Script fixtures only; audio unavailable; not BTC audio.',
                              'review_status': 'pending_human_listening', 'voices': None if args.voicemaker_scripts else VOICES,
                              'dialogues': [d for d in data if d['split'] == split]})
        print('Scripts/GT prepared; no TTS requested; audio remains unavailable.', flush=True)
        return
    cache = args.out / 'tts-cache'
    cache.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(1)

    async def synth(turn):
        voice = VOICES[turn['speaker']]
        key = hashlib.sha256((voice + turn['text']).encode()).hexdigest()
        path = cache / (key + '.mp3')
        original_cache = ROOT/'datasets/synthetic-v1/tts-cache'/path.name
        if args.phone_variants and original_cache.exists():
            return decode(original_cache)  # Read-only reuse of unchanged original utterances.
        if not path.exists():
            async with semaphore:
                partial = path.with_suffix('.partial')
                for attempt in range(5):
                    try:
                        await edge_tts.Communicate(turn['text'], voice).save(str(partial))
                        decode(partial)  # Reject an empty/invalid response before caching it.
                        break
                    except (edge_tts.exceptions.NoAudioReceived, OSError):
                        if attempt == 4:
                            raise
                        print('TTS retry',voice,key[:8],attempt+1,flush=True)
                        await asyncio.sleep(5 * (attempt + 1))
                partial.replace(path)
        return decode(path)

    for d in data:
        audio = args.out / d['split'] / 'audio' / (d['id'] + '.wav')
        if audio.exists():
            if not audio.with_suffix('.segments.json').exists():
                raise ValueError('Audio exists without generation metadata: ' + str(audio))
            print('Reuse', d['id'], flush=True)
            continue
        pieces, segments, offset = [], [], 0
        for turn, pcm in zip(d['turns'], await asyncio.gather(*(synth(t) for t in d['turns']))):
            segments.append({'speaker': turn['speaker'], 'start': offset / RATE,
                             'end': (offset + len(pcm)) / RATE, 'text': turn['text']})
            pieces.extend([pcm, np.zeros(int(RATE * .3), dtype=np.float32)])
            offset += len(pcm) + int(RATE * .3)
        samples = np.concatenate(pieces)
        if d['noisy']:
            # Synthetic telephone band limitation + white noise, not real telephone recordings.
            freq = np.fft.rfftfreq(len(samples), 1 / RATE)
            spectrum = np.fft.rfft(samples)
            spectrum[(freq < 300) | (freq > 3400)] = 0
            samples = np.fft.irfft(spectrum, n=len(samples))
            rng = np.random.default_rng(int(d['id'].split('-')[-1]))
            samples += rng.normal(0, np.sqrt(np.mean(samples ** 2)) / 10, len(samples))
        audio.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(audio), 'wb') as f:
            f.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
            f.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())
        save(audio.with_suffix('.segments.json'), {'source': 'synthetic_tts_boundaries_not_human_verified', 'segments': segments})
        print('Generated', d['id'], round(len(samples) / RATE, 1), 'seconds', flush=True)
    for split in ('dev', 'eval'):
        ground_truth = args.out / split / 'ground_truth.json'
        if ground_truth.exists():
            print('Keep existing GT (including review status)', split, flush=True)
            continue
        save(ground_truth, {
            'description': 'Team synthetic smoke-test corpus. Script-derived GT awaits human listening; not BTC audio.',
            'review_status': 'pending_human_listening', 'voices': VOICES,
            'normalization_rule': 'Raw BTC scorer plus separately versioned numeric-word view recorded in each run manifest.',
            'dialogues': [d for d in data if d['split'] == split]})


if __name__ == '__main__':
    asyncio.run(main())
