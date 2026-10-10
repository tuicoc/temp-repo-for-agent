"""Three short regional voice samples; no ASR, no bulk generation, stdlib only."""
import json
from pathlib import Path
import time
import ssl
import certifi
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent
TLS = ssl.create_default_context(cafile=certifi.where())
TEXT = ('Xin chào, đây là bản thử giọng tiếng Việt. Giá sản phẩm là bốn triệu tám trăm chín mươi nghìn đồng. '
        'Số điện thoại giả lập: không chín không, một ba tám, năm bảy hai bốn. Mình hẹn gọi lại vào ngày mai.')


def main():
    keys = [s.split('=', 1)[1].strip() for s in (ROOT/'.env.local').read_text().splitlines()
            if s.startswith('FPT_TTS_API_KEY=')]
    if len(keys) != 1 or not keys[0]:
        raise ValueError('Missing or duplicate API key; not printing credentials')
    key = keys[0]
    folder = ROOT/'output/fpt-voice-samples-v1'
    folder.mkdir(parents=True, exist_ok=True)
    cards = []
    for voice, region in (('banmai', 'Bắc'), ('giahuy', 'Trung'), ('lannhi', 'Nam')):
        target = folder/f'{voice}.mp3'
        if not target.exists():
            print('Request', voice, len(TEXT), 'characters', flush=True)
            request = Request('https://api.fpt.ai/hmi/tts/v5', data=TEXT.encode('utf-8'),
                              headers={'api_key': key, 'voice': voice, 'speed': '0', 'format': 'mp3'}, method='POST')
            try:
                with urlopen(request, timeout=30, context=TLS) as response:
                    result = json.load(response)
            except (HTTPError, URLError) as error:
                reason = str(getattr(error, 'reason', 'Request failed')).replace(key, '[REDACTED]')
                print('API unavailable:', getattr(error, 'code', type(error).__name__), reason, flush=True)
                return 2
            if result.get('error') != 0 or not str(result.get('async', '')).startswith('https://'):
                message = str(result.get('message', 'No audio URL')).replace(key, '[REDACTED]')
                print('API rejected:', result.get('error'), message, flush=True)
                return 2
            for attempt in range(24):
                try:
                    with urlopen(result['async'], timeout=20, context=TLS) as response:
                        payload = response.read()
                    if len(payload) < 100 or not (payload.startswith(b'ID3') or payload[0] == 255):
                        raise ValueError('Not a valid-looking MP3 response')
                    target.write_bytes(payload)
                    break
                except (HTTPError, URLError, ValueError):
                    if attempt == 23:
                        print('Audio not ready; do not resubmit POST automatically', flush=True)
                        return 2
                    time.sleep(5)
            print('Saved', target, flush=True)
        cards.append(f'<h2>{region} — {voice}</h2><audio controls src="{voice}.mp3"></audio>')
        (folder/'listen.html').write_text('<meta charset="utf-8"><h1>Thử ba giọng FPT</h1>'
                                        + '<p>'+TEXT+'</p>' + ''.join(cards), encoding='utf-8')
    print('Listen:', folder/'listen.html')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
