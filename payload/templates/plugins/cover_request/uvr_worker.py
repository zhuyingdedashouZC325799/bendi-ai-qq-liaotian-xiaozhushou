"""Run UVR5 in the modern CUDA runtime, keeping the user's installations untouched."""
from portable_settings import remap as _portable_path, owners as _portable_owners, settings as _portable_settings, speaker_policy as _portable_speaker, text as _portable_text, port as _portable_port, cache_for as _portable_cache
import argparse
import functools
import inspect
import os
from pathlib import Path
import sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    args = parser.parse_args()
    legacy = Path(_portable_path('D:/RVC20240604Nvidia50x0'))
    os.chdir(legacy)
    sys.path.insert(0, str(legacy))
    print('UVR5 loading librosa', flush=True)
    import librosa
    for name in ('load', 'resample', 'stft', 'istft'):
        original = getattr(librosa, name)
        params = list(inspect.signature(original).parameters)

        def adapter(*values, _fn=original, _names=params, **kw):
            for key, value in zip(_names, values):
                if key in kw:
                    raise TypeError('duplicate ' + key)
                kw[key] = value
            return _fn(**kw)
        wrapped = functools.wraps(original)(adapter)
        setattr(librosa, name, wrapped)
        setattr(librosa.core, name, wrapped)
    print('UVR5 loading torch', flush=True)
    import torch
    torch.set_num_threads(4)
    from infer.modules.uvr5.vr import AudioPre
    output = Path(args.output)
    (output / 'vocals').mkdir(parents=True, exist_ok=True)
    (output / 'instrumental').mkdir(exist_ok=True)
    if args.device == 'cuda' and (not torch.cuda.is_available()):
        raise RuntimeError('CUDA unavailable')
    device = 'cuda:0' if args.device == 'cuda' and torch.cuda.is_available() else 'cpu'
    print('UVR5: device=' + device, flush=True)
    engine = AudioPre(agg=10, model_path=str(Path(_portable_settings()['models_dir']) / 'uvr5/HP2_all_vocals.pth'), device=device, is_half=False)
    engine._path_audio_(args.input, str(output / 'instrumental'), str(output / 'vocals'), 'wav', is_hp3=False)
    vocals = list((output / 'vocals').glob('*.wav'))
    instrumental = list((output / 'instrumental').glob('*.wav'))
    if len(vocals) != 1 or len(instrumental) != 1:
        raise RuntimeError('UVR5 did not produce both stems')
    import json
    (output / 'stems.json').write_text(json.dumps({'vocals': str(vocals[0]), 'instrumental': str(instrumental[0])}), encoding='utf-8')
    print('UVR5 SUCCESS', flush=True)
if __name__ == '__main__':
    main()
