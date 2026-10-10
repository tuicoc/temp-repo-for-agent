"""Offline ASR runner and unmodified BTC scoring, with explicit coverage."""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import sys
import time
import wave
from importlib.metadata import version

from text_processing import VERSION, extract, normalize, callback_date

ROOT = Path(__file__).resolve().parent
SCORER = ROOT.parent / 'evaluation-contracts/sources/btc/eval/reference_eval.py'
PROFILES = ('baseline', 'vad', 'vad-prompt', 'phone-refine')
PROMPT = 'Hội thoại tư vấn tiếng Việt. Số điện thoại được đọc từng chữ số: không, một, hai, ba, bốn, năm, sáu, bảy, tám, chín. Giá tiền và ngân sách tính bằng đồng.'


def recognize(model, path, profile):
    """Only audio + pinned generic configuration enter recognition; never GT boundaries."""
    from faster_whisper.audio import decode_audio
    audio = decode_audio(str(path))
    windows = [{'start': 0, 'end': len(audio)}]
    if profile in ('vad', 'vad-prompt'):
        from faster_whisper.vad import get_speech_timestamps, VadOptions
        windows = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=350,
                                      speech_pad_ms=180, max_speech_duration_s=15))
        if not windows:
            raise ValueError('VAD found no speech; no silent fallback')
    segments = []
    for window in windows:
        parts, _ = model.transcribe(audio[window['start']:window['end']], language='vi', beam_size=5,
                                   condition_on_previous_text=False, vad_filter=False,
                                   no_speech_threshold=None, log_prob_threshold=None,
                                   initial_prompt=PROMPT if profile == 'vad-prompt' else None)
        offset = window['start'] / 16000
        segments.extend({'start': s.start + offset, 'end': s.end + offset, 'text': s.text} for s in parts)
    return segments, [{'start': w['start']/16000, 'end': w['end']/16000} for w in windows]


def refine_phone(model, path, segments):
    """Retry only a phone span located in ASR output, preserving every raw candidate."""
    from faster_whisper.audio import decode_audio
    audio = decode_audio(str(path))
    trials = []
    for index, s in enumerate(segments):
        if 'điện thoại' not in s['text'].lower():
            continue
        original, problems = extract(s['text'])
        if 'phone' in original:
            continue
        start = max(0, s['start'] - .25)
        end = min(len(audio)/16000, s['end'] + .5)
        parts, _ = model.transcribe(audio[int(start*16000):int(end*16000)], language='vi', beam_size=5,
                                   condition_on_previous_text=False, no_speech_threshold=None,
                                   log_prob_threshold=None, initial_prompt='Số điện thoại được đọc từng chữ số.')
        candidate = ' '.join(p.text.strip() for p in parts)
        found, diagnostics = extract(candidate)
        accepted = 'phone' in found
        trials.append({'segment_index':index, 'start':start, 'end':end, 'primary_text':s['text'],
                       'candidate_text':candidate, 'diagnostics':diagnostics, 'accepted':accepted})
        if accepted:
            segments[index] = {**s, 'text':candidate}
    return segments, trials


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def unique_object(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError('Duplicate JSON key: ' + k)
        result[k] = v
    return result


def read(path):
    def invalid_constant(value):
        raise ValueError('Non-finite JSON number: ' + value)
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object, parse_constant=invalid_constant)


def preflight(dataset):
    gt = read(dataset / 'ground_truth.json')
    if not isinstance(gt, dict) or not isinstance(gt.get('dialogues'), list) or not gt['dialogues']:
        raise ValueError('Expected a non-empty dialogues array')
    ids, audio, issues = [], [], []
    for d in gt['dialogues']:
        if not isinstance(d, dict) or not isinstance(d.get('id'), str) or not isinstance(d.get('full_text'), str):
            raise ValueError('Each dialogue needs string id and full_text')
        key = d['id']
        if not isinstance(key, str) or not key or key in ('.', '..') or Path(key).name != key or key in ids:
            raise ValueError('Invalid/duplicate dialogue ID: ' + str(key))
        if not isinstance(d['full_text'], str) or not normalize(d['full_text']):
            raise ValueError('Empty reference: ' + key)
        if not isinstance(d.get('entities', {}), dict):
            raise ValueError('Expected entity dictionary: ' + key)
        if any(not isinstance(v, (str, int, float, bool, type(None))) for v in d.get('entities', {}).values()):
            raise ValueError('Entity values must be scalar: ' + key)
        if any(isinstance(v, float) and not math.isfinite(v) for v in d.get('entities', {}).values()):
            raise ValueError('Entity numbers must be finite: ' + key)
        if d.get('call_date') is not None:
            from datetime import date
            date.fromisoformat(d['call_date'])
        supplemental = d.get('supplemental_entities', {})
        if not isinstance(supplemental, dict) or set(supplemental) - {'callback_date'}:
            raise ValueError('Only supplemental callback_date is supported: ' + key)
        if 'callback_date' in supplemental:
            from datetime import date
            date.fromisoformat(supplemental['callback_date'])
        ids.append(key)
        path = dataset / 'audio' / (key + '.wav')
        try:
            with wave.open(str(path)) as f:
                frames = f.getnframes()
                seconds = frames / f.getframerate()
                if f.getnchannels() != 1 or f.getsampwidth() != 2 or f.getframerate() != 16000 or seconds <= 0:
                    raise ValueError('Expected non-empty PCM16 mono 16kHz WAV')
                if len(f.readframes(frames)) != frames * 2:
                    raise ValueError('Truncated WAV payload')
            audio.append({'id': key, 'path': str(path.resolve()), 'sha256': sha(path), 'seconds': seconds})
        except (OSError, ValueError, wave.Error, EOFError) as e:
            issues.append({'id': key, 'kind': 'AUDIO_UNAVAILABLE', 'detail': str(e)})
    for path in (dataset/'audio').glob('*.wav'):
        if path.stem not in ids:
            issues.append({'id': path.stem, 'kind': 'UNEXPECTED_AUDIO'})
    return gt, ids, audio, issues


def timing_summary(samples):
    effective = [s for s in samples if not s.get('warmup', False)]
    seconds = sum(s['audio_seconds'] for s in effective)
    return {'samples': len(samples), 'raw_sample_count': len(samples),
            'effective_sample_count': len(effective),
            'warmup_sample_count': len(samples) - len(effective),
            'asr_seconds_per_audio_minute': sum(s['elapsed_seconds'] for s in effective) / (seconds / 60) if seconds else None}


def validate_hypotheses(hypothesis):
    from jsonschema import Draft202012Validator
    schema = read(ROOT.parent / 'evaluation-contracts/contracts.schema.json')['$defs']['AsrHypotheses']
    problems, valid = [], {}
    if not isinstance(hypothesis, dict):
        return {}, [{'kind': 'INVALID_HYPOTHESES', 'detail': 'Root must be an ID dictionary'}]
    validator = Draft202012Validator(schema)
    for key, h in hypothesis.items():
        errors = list(validator.iter_errors({key: h}))
        if errors or not isinstance(h.get('text'), str) or not normalize(h['text']):
            problems.append({'id': key, 'kind': 'INVALID_HYPOTHESIS',
                             'detail': '; '.join(e.message for e in errors) or 'Empty transcript'})
        else:
            valid[key] = h
    return valid, problems


def coverage(expected, raw, valid, issues):
    raw = raw if isinstance(raw, dict) else {}
    missing = sorted(set(expected) - set(valid))
    unknown = sorted(set(raw) - set(expected))
    complete = not (missing or unknown or issues)
    return {'expected': len(expected), 'observed': len(set(expected) & set(valid)),
            'missing_ids': missing, 'unknown_ids': unknown, 'complete': complete,
            'status': 'COMPLETE' if complete else 'INCOMPLETE'}


def entity_accuracy(gt, hyp):
    counts = {}
    for d in gt['dialogues']:
        for key, value in d.get('entities', {}).items():
            kind = 'phone' if 'phone' in key or 'sdt' in key else 'money' if any(x in key for x in ('price', 'budget', 'vnd')) else key
            c = counts.setdefault(kind, {'correct': 0, 'total': 0})
            c['total'] += 1
            c['correct'] += int(str(hyp.get(d['id'], {}).get('entities', {}).get(key)) == str(value))
    for c in counts.values():
        c['accuracy'] = round(100 * c['correct'] / c['total'], 1)
    return counts


def score(out, gt, hyp, segment_references=None):
    # Loading the immutable scorer must not create __pycache__ inside its source snapshot.
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('btc_asr', SCORER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ('raw', 'normalized'):
        folder = out / name
        ref = json.loads(json.dumps(gt))
        predictions = json.loads(json.dumps(hyp))
        if name == 'normalized':
            for d in ref['dialogues']:
                d['full_text'] = normalize(d['full_text'])
            for h in predictions.values():
                h['text'] = normalize(h['text'])
        save(folder / 'ground_truth.json', ref)
        save(folder / 'hypotheses.json', predictions)
        # These labels are consumed only by the scorer, after inference is complete.
        for d in ref['dialogues']:
            if d['id'] in predictions and predictions[d['id']].get('turns'):
                if segment_references and d['id'] in segment_references:
                    save(folder/'audio'/f"{d['id']}.segments.json", segment_references[d['id']])
        save(folder / 'btc_metrics.json', module.wer_cer(str(folder)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', type=Path, required=True)
    ap.add_argument('--model', type=Path, default=ROOT / 'models/faster-whisper-small')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--hypotheses', type=Path, help='Replay only; no ASR speed claim')
    ap.add_argument('--profile', choices=PROFILES, default='baseline')
    ap.add_argument('--reextract', action='store_true', help='Replay raw texts through current extractor')
    ap.add_argument('--lock', type=Path, help='Pin runtime/model/code from a completed dev run')
    ap.add_argument('--diarization', action='store_true', help='M2 experimental acoustic two-speaker baseline; agent-first protocol')
    ap.add_argument('--warmup', type=int, default=3, help='Exclude first N samples from timing only; quality still scored')
    ap.add_argument('--expected-count', type=int, help='Fail preflight if GT count differs from declared suite size')
    args = ap.parse_args()
    if args.out.exists():
        ap.error('Output already exists; choose a fresh run directory to preserve evidence.')
    if args.reextract and not args.hypotheses:
        ap.error('--reextract requires --hypotheses')
    if args.warmup < 0:
        ap.error('--warmup must be non-negative')
    gt, expected, audio, issues = preflight(args.dataset)
    if args.expected_count is not None and len(expected) != args.expected_count:
        ap.error('GT dialogue count differs from --expected-count')
    args.out.mkdir(parents=True)
    manifest = {'mode': 'replay' if args.hypotheses else 'local_asr', 'profile': args.profile, 'platform': platform.platform(),
                'dataset': str(args.dataset.resolve()), 'ground_truth_sha256': sha(args.dataset / 'ground_truth.json'),
                'scorer_sha256': sha(SCORER), 'normalizer': VERSION,
                'parameters': {'language': 'vi', 'beam_size': 5, 'device': 'cpu', 'compute_type': 'int8',
                               'cpu_threads': 4, 'vad_filter': False, 'condition_on_previous_text': False,
                               'no_speech_threshold': None, 'log_prob_threshold': None},
                'audio': audio, 'expected_ids': expected,
                'review_status': gt.get('review_status', 'unverified'),
                'warmup_samples': args.warmup,
                'declared_expected_count': args.expected_count,
                'versions': {n: version(n) for n in ('faster-whisper', 'ctranslate2', 'av')}}
    manifest['code_hashes'] = {p.name: sha(p) for p in (Path(__file__), ROOT/'text_processing.py')}
    manifest['diarization'] = 'acoustic-two-speaker-v1' if args.diarization else None
    if args.diarization:
        manifest['code_hashes']['diarize.py'] = sha(ROOT/'diarize.py')
    manifest['vad_parameters'] = {'min_silence_duration_ms': 350, 'speech_pad_ms': 180, 'max_speech_duration_s': 15} if args.profile in ('vad', 'vad-prompt') else None
    manifest['initial_prompt'] = PROMPT if args.profile == 'vad-prompt' else None
    manifest['phone_refinement'] = ({'max_attempts_per_span':1, 'locator':'primary ASR segment containing điện thoại',
                                     'prompt':'Số điện thoại được đọc từng chữ số.', 'acceptance':'exactly 10 digits starting with 0'}
                                   if args.profile == 'phone-refine' else None)
    save(args.out / 'manifest.json', manifest)
    timing, hypothesis = [], {}
    if args.hypotheses:
        hypothesis = read(args.hypotheses)
        save(args.out / 'submitted_hypotheses.json', hypothesis)
        manifest['replay_sha256'] = sha(args.hypotheses)
        if args.reextract and isinstance(hypothesis, dict):
            for key, h in hypothesis.items():
                if isinstance(h, dict) and isinstance(h.get('text'), str):
                    h['entities'], diagnostics = extract(h['text'])
                    save(args.out / 'extraction' / (hashlib.sha256(key.encode()).hexdigest()+'.json'), diagnostics)
        save(args.out / 'manifest.json', manifest)
    else:
        from faster_whisper import WhisperModel
        manifest['model_files'] = {p.name: sha(p) for p in args.model.iterdir() if p.is_file()}
        pinned = {k:manifest[k] for k in ('profile','normalizer','parameters','versions','code_hashes',
                                         'model_files','scorer_sha256','vad_parameters','initial_prompt','phone_refinement','diarization','warmup_samples')}
        if args.lock and read(args.lock) != pinned:
            raise ValueError('Configuration differs from dev lock; do not evaluate until revalidated on dev')
        save(args.out / 'config.lock.json', pinned)
        started = time.perf_counter()
        model = WhisperModel(str(args.model.resolve()), device='cpu', compute_type='int8', cpu_threads=4, local_files_only=True)
        manifest['model_load_seconds'] = time.perf_counter() - started
        save(args.out / 'manifest.json', manifest)
        # Recognition receives audio paths, never GT text, entity labels, or TTS segment boundaries.
        for index, a in enumerate(audio):
            started = time.perf_counter()
            try:
                segments, windows = recognize(model, a['path'], args.profile)
                save(args.out / 'primary_segments' / (a['id'] + '.json'), segments)
                if args.profile == 'phone-refine':
                    segments, trials = refine_phone(model, a['path'], segments)
                    save(args.out / 'phone_retries' / (a['id'] + '.json'), trials)
                text = ' '.join(s['text'].strip() for s in segments)
                extracted, diagnostics = extract(text)
                hypothesis[a['id']] = {'text': text, 'entities': extracted}
                if args.diarization:
                    from diarize import predict
                    turns, meta = predict(a['path'])
                    hypothesis[a['id']]['turns'] = turns
                    save(args.out/'diarization'/f"{a['id']}.json",meta)
                save(args.out / 'segments' / (a['id'] + '.json'), segments)
                save(args.out / 'extraction' / (a['id'] + '.json'), diagnostics)
                save(args.out / 'vad' / (a['id'] + '.json'), windows)
                timing.append({'id': a['id'], 'audio_seconds': a['seconds'], 'elapsed_seconds': time.perf_counter() - started,
                               'warmup': index < args.warmup})
                print('Transcribed', a['id'], round(timing[-1]['elapsed_seconds'], 2), 'seconds', flush=True)
            except Exception as e:
                issues.append({'id': a['id'], 'kind': 'ASR_ERROR', 'detail': str(e)})
            save(args.out / 'hypotheses.json', hypothesis)
    raw_hypothesis = copy.deepcopy(hypothesis)
    hypothesis, invalid = validate_hypotheses(hypothesis)
    issues.extend(invalid)
    measured_coverage = coverage(expected, raw_hypothesis, hypothesis, issues)
    hypothesis = {k: v for k, v in hypothesis.items() if k in expected}
    save(args.out / 'hypotheses.json', hypothesis)
    save(args.out / 'coverage.json', measured_coverage)
    segment_references = {}
    if args.diarization:
        for d in gt['dialogues']:
            ref_path = args.dataset/'audio'/f"{d['id']}.segments.json"
            if ref_path.exists():
                segment_references[d['id']] = read(ref_path)
            else:
                issues.append({'id':d['id'],'kind':'DIARIZATION_GT_MISSING'})
                measured_coverage.update(complete=False,status='INCOMPLETE')
        save(args.out/'coverage.json',measured_coverage)
    score(args.out, gt, hypothesis, segment_references)
    supplemental_gt, supplemental_hyp = {'dialogues': []}, {}
    for d in gt['dialogues']:
        predicted, problems = callback_date(hypothesis.get(d['id'], {}).get('text', ''),
                                            d.get('call_date', gt.get('reference_date')))
        supplemental_gt['dialogues'].append({'id': d['id'], 'entities': d.get('supplemental_entities', {})})
        supplemental_hyp[d['id']] = {'entities': predicted}
        save(args.out/'supplemental'/f"{d['id']}.json", {'entities': predicted, 'diagnostics': problems})
    complete = measured_coverage['complete']
    reviewed = manifest['review_status'] == 'human_verified' and all(d.get('review_status') == 'human_verified' for d in gt['dialogues'])
    scored = read(args.out / 'normalized/btc_metrics.json')
    entity_types = entity_accuracy(gt, hypothesis)
    for d in gt['dialogues']:
        h = hypothesis.get(d['id'])
        if h is None:
            continue
        mismatches = {k: {'expected': v, 'actual': h.get('entities', {}).get(k)} for k, v in d.get('entities', {}).items()
                      if str(h.get('entities', {}).get(k)) != str(v)}
        metric = scored['per_dialogue'][d['id']]
        if metric['wer'] or mismatches:
            issues.append({'id': d['id'], 'kind': 'RECOGNITION_MISMATCH', 'wer': metric['wer'],
                           'entities': mismatches, 'reference': d['full_text'], 'hypothesis': h['text']})
        for key, difference in mismatches.items():
            stage = 'EXTRACTOR_UNSUPPORTED' if key not in ('phone','price_vnd','budget_vnd') else 'ASR_OR_GT_REQUIRES_LISTENING'
            issues.append({'id':d['id'], 'kind':stage, 'entity':key, **difference})
    report = {'report_schema_version': '1.3.0',
              'coverage': measured_coverage,
              'inventory': {'expected_dialogues': len(expected), 'expected_turns': sum(len(d.get('turns', [])) for d in gt['dialogues']),
                            'expected_entities': sum(len(d.get('entities', {})) for d in gt['dialogues']),
                            'observed_hypotheses': len(set(expected) & hypothesis.keys()),
                            'observed_entities': sum(len(h.get('entities', {})) for h in hypothesis.values()),
                            'noisy_dialogues': sum(bool(d.get('noisy')) for d in gt['dialogues']),
                            'regions': sorted({d.get('region', 'unverified') for d in gt['dialogues']}),
                            'audio_minutes': round(sum(a['seconds'] for a in audio) / 60, 3)},
              'acceptance': 'UNDETERMINED' if complete else 'INCOMPLETE', 'reason': 'No quality threshold configured; human listening review is reported separately.',
              'human_review_complete': reviewed, 'btc_audio_evaluated': False,
              'timing': {**timing_summary(timing), 'model_load_seconds': manifest.get('model_load_seconds')},
              'raw_metrics': read(args.out / 'raw/btc_metrics.json'), 'normalized_metrics': scored,
              'supplemental_entity_accuracy': entity_types,
              'supplemental_callback_accuracy': entity_accuracy(supplemental_gt, supplemental_hyp) or None,
              'supplemental_entity_formula': '100 * correct exact-match / all GT entities of that type; missing hypotheses count incorrect',
              'limitations': ['ITN v3: phone and integer VND; callback dates are supplemental and require declared call date for relative forms. SKU/area remain unsupported.',
                             'Synthetic TTS is not representative human/noisy-call evaluation.',
                             'Experimental acoustic diarization; not validated for real calls.' if args.diarization else 'M1 only: no diarization inference.',
                             'TTS timing labels are never ASR predictions.']}
    save(args.out / 'report.json', report)
    save(args.out / 'timing.json', timing)
    save(args.out / 'errors.json', issues)
    print(json.dumps({'coverage': report['coverage'], 'WER': scored['WER'], 'CER': scored['CER'], 'entity_accuracy': scored['entity_accuracy']}, ensure_ascii=False))
    return 0 if complete else 2


if __name__ == '__main__':
    raise SystemExit(main())
