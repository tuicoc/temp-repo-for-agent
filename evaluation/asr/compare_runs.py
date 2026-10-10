"""Compare frozen run reports without changing metrics or selecting from eval."""
import argparse
import json
from pathlib import Path

from run_eval import read, save, sha


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--before', type=Path, required=True)
    ap.add_argument('--after', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        ap.error('Comparison output exists; choose a fresh directory')
    before, after = (read(p/'report.json') for p in (args.before, args.after))
    bm, am = (read(p/'manifest.json') for p in (args.before, args.after))
    if bm['ground_truth_sha256'] != am['ground_truth_sha256'] or bm['expected_ids'] != am['expected_ids']:
        ap.error('Different GT or cohorts: comparison is not paired')
    if {a['id']:a['sha256'] for a in bm['audio']} != {a['id']:a['sha256'] for a in am['audio']}:
        ap.error('Audio content changed; paired comparison invalid')
    if not before['coverage']['complete'] or not after['coverage']['complete']:
        ap.error('Incomplete run: resolve coverage before paired comparison')
    rows = []
    for key in ('WER','CER','entity_accuracy'):
        b,a = before['normalized_metrics'][key], after['normalized_metrics'][key]
        rows.append({'metric':key, 'before':b, 'after':a, 'delta_percentage_points':round(a-b,2) if a is not None and b is not None else None})
    for kind in ('money','phone'):
        b = before.get('supplemental_entity_accuracy',{}).get(kind,{}).get('accuracy')
        a = after.get('supplemental_entity_accuracy',{}).get(kind,{}).get('accuracy')
        rows.append({'metric':kind+'_accuracy', 'before':b, 'after':a,
                     'delta_percentage_points':round(a-b,2) if a is not None and b is not None else None})
    save(args.out/'comparison.json', {'before':str(args.before), 'after':str(args.after),
         'report_hashes':[sha(p/'report.json') for p in (args.before,args.after)], 'rows':rows,
         'same_audio':True, 'same_GT':True, 'quality_acceptance':'UNDETERMINED',
         'normalizer_versions':[bm['normalizer'],am['normalizer']],
         'note':'Percentages are on synthetic data pending human listening; delta is percentage points, not relative reduction.'})
    text = '# So sánh ASR trước–sau\n\nCùng hash audio và GT, đủ coverage. Dữ liệu TTS còn chờ nghe duyệt.\n\n'
    text += '| Chỉ số (%) | Trước | Sau | Delta (điểm %) |\n|---|---:|---:|---:|\n'
    text += ''.join(f"| {r['metric']} | {r['before']} | {r['after']} | {r['delta_percentage_points']} |\n" for r in rows)
    text += '\nXem lỗi cụ thể trong `errors.json` và nghe xác nhận trên `listen.html`. Không suy ra cải thiện trên audio thật từ bộ TTS này. Replay không có timing ASR để so tốc độ.\n'
    (args.out/'comparison.md').write_text(text,encoding='utf-8')
    print(args.out/'comparison.md')


if __name__ == '__main__':
    main()
