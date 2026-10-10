"""Create a fully offline listening page; only this UI may read synthetic turn labels."""
import argparse
import html
import json
from pathlib import Path
import wave

from run_eval import read, save, sha

ROOT = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', type=Path, default=ROOT/'datasets/synthetic-v1')
    args = ap.parse_args()
    cards, inventory = [], []
    for split in ('dev', 'eval'):
        gt = read(args.dataset/split/'ground_truth.json')
        for d in gt['dialogues']:
            key = d['id']
            path = args.dataset/split/'audio'/f'{key}.wav'
            with wave.open(str(path)) as w:
                seconds = w.getnframes()/w.getframerate()
            segments = read(path.with_suffix('.segments.json'))['segments']
            phone_turn = next((s for s in segments if 'điện thoại' in s['text']), None)
            inventory.append({'id':key, 'audio_sha256':sha(path), 'seconds':seconds,
                              'review_status':'pending_human_listening', 'note':''})
            esc = html.escape
            rows = ''.join(f'<li><b>{esc(s["speaker"])}</b>: {esc(s["text"])}</li>' for s in segments)
            snippet = (f'<button onclick="playPhone(this,{phone_turn["start"]},{phone_turn["end"]})">Nghe riêng SĐT</button>' if phone_turn else '')
            cards.append(f'''<article data-id="{esc(key)}" data-split="{split}">
              <h2>{esc(key)} <small>{split} · {seconds:.1f}s · {'nhiễu' if d.get('noisy') else 'clean'}</small></h2>
              <audio controls preload="none" src="{split}/audio/{esc(key)}.wav"></audio>{snippet}
              <p>Đáp án script: <code>{esc(json.dumps(d.get('entities',{}),ensure_ascii=False))}</code></p>
              <details><summary>Transcript dự kiến — cần nghe xác nhận</summary><ol>{rows}</ol></details>
              <label><input type="checkbox"> Tôi đã nghe và xác nhận audio khớp transcript + entity</label>
              <textarea placeholder="Nếu sai: ghi chữ số/từ thực sự nghe được; chưa xác nhận thì để ô trên trống"></textarea>
              </article>''')
    save(args.dataset/'review-inventory.json', inventory)
    data = json.dumps(inventory,ensure_ascii=False).replace('<','\\u003c')
    page = '''<!doctype html><html lang="vi"><meta charset="utf-8"><title>Nghe duyệt ASR</title>
    <style>body{font:16px system-ui;margin:32px auto;max-width:1000px;padding:0 16px;background:#f5f7fb;color:#15263b}
    article{background:white;border:1px solid #d9e2ee;border-radius:12px;padding:20px;margin:18px 0}audio{display:block;width:100%;margin:12px 0}
    h2{font-size:20px}small{font-size:14px;color:#617287}textarea{width:98%;min-height:65px;display:block;margin-top:10px}button,select{padding:9px;margin:8px 8px 8px 0}li{margin:6px 0}label{display:block}</style>
    <h1>Nghe audio và duyệt đáp án</h1><p>__COUNT__ audio TTS. Mọi case đang chờ bạn nghe xác nhận. Đoạn cắt SĐT lấy từ nhãn sinh TTS để hỗ trợ nghe; ASR không dùng nhãn này.</p>
    <select onchange="filter(this.value)"><option value="all" selected>Tất cả</option><option value="dev">Dev</option><option value="eval">Eval / diagnostic</option></select>
    <button onclick="exportReview()">Tải phiếu nghe duyệt JSON</button><p>Phiếu tải về ghi hash audio và xác nhận của bạn. GT gốc giữ nguyên; nếu phát hiện sai, cần tạo dataset phiên bản mới trước khi đo lại.</p>
    __CARDS__
    <script>const inventory=__DATA__;let activeTimer;
    function playPhone(button,start,end){clearInterval(activeTimer);const a=button.closest('article').querySelector('audio');a.currentTime=start;a.play();activeTimer=setInterval(()=>{if(a.currentTime>=end){a.pause();clearInterval(activeTimer)}},50)}
    function filter(split){document.querySelectorAll('article').forEach(c=>c.hidden=split!=='all'&&c.dataset.split!==split)}
    function exportReview(){const cards=[...document.querySelectorAll('article')];const result=inventory.map((r,i)=>({...r,review_status:cards[i].querySelector('input').checked?'human_verified':'pending_human_listening',note:cards[i].querySelector('textarea').value}));const u=URL.createObjectURL(new Blob([JSON.stringify({reviewed_at:new Date().toISOString(),dialogues:result},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='asr-listening-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}filter('dev');</script></html>'''
    page = page.replace("filter('dev');", "filter('all');")
    (args.dataset/'listen.html').write_text(page.replace('__COUNT__',str(len(cards))).replace('__CARDS__',''.join(cards)).replace('__DATA__',data),encoding='utf-8')
    print(args.dataset/'listen.html')


if __name__ == '__main__':
    main()
