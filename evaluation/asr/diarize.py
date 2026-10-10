"""Local two-speaker acoustic baseline; no GT boundaries or TTS speaker labels."""
import numpy as np

VERSION = 'acoustic-two-speaker-v1'


def voice_feature(audio):
    pitches, centroids = [], []
    for start in range(0,len(audio)-1024,512):
        frame = audio[start:start+1024].astype(float)
        frame -= frame.mean()
        if np.sqrt(np.mean(frame*frame)) < .006:
            continue
        spectrum = np.abs(np.fft.rfft(frame*np.hanning(len(frame))))
        ac = np.fft.irfft(np.abs(np.fft.rfft(frame,n=2048))**2)
        lag = 45 + np.argmax(ac[45:268])
        if ac[0] and ac[lag]/ac[0]>.35:
            pitches.append(np.log(16000/lag))
        centroids.append(np.log((spectrum @ np.fft.rfftfreq(1024,1/16000))/(spectrum.sum()+1e-9)+1))
    if not pitches or not centroids:
        return None
    return np.array([np.median(pitches),np.median(centroids)])


def predict(audio_path):
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    audio = decode_audio(str(audio_path))
    windows = get_speech_timestamps(audio,VadOptions(min_silence_duration_ms=350,speech_pad_ms=180))
    features = [voice_feature(audio[w['start']:w['end']]) for w in windows]
    valid = [i for i,x in enumerate(features) if x is not None]
    if len(valid)<2 or len(valid)!=len(windows):
        raise ValueError('Insufficient voiced evidence for every diarization segment')
    x = np.array(features)
    # ponytail: pitch/timbre baseline for two synthetic voices; learned speaker embeddings needed for similar voices/overlap.
    x = (x-x.mean(axis=0))/np.maximum(x.std(axis=0),.05)
    centers = x[[np.argmin(x[:,0]),np.argmax(x[:,0])]].copy()
    for _ in range(20):
        labels = ((x[:,None,:]-centers[None,:,:])**2).sum(axis=2).argmin(axis=1)
        if len(set(labels))!=2:
            raise ValueError('Cannot establish two distinct speaker clusters')
        updated = np.array([x[labels==k].mean(axis=0) for k in range(2)])
        if np.allclose(updated,centers): break
        centers=updated
    # Declared protocol: first speaking voice is agent A; never remap using scoring labels.
    agent = labels[0]
    turns = [{'start':w['start']/16000,'end':w['end']/16000,'speaker':'A' if label==agent else 'C'}
             for w,label in zip(windows,labels)]
    return turns, {'version':VERSION,'role_policy':'agent-first','feature':'median_log_F0_and_spectral_centroid',
                   'centers':centers.tolist(), 'n_segments':len(turns),
                   'limitations':['Exactly two voices; first speaker must be agent; overlap and similar voices unsupported.']}
