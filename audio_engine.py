"""音频引擎 - 精简稳定版"""
import json, logging, os, queue, re, threading, time, traceback
from datetime import datetime
from typing import Callable, Optional
import ahocorasick, numpy as np, sounddevice as sd
from models import ViolationEvent
from config import (FORBIDDEN_WORDS, AUDIO_CONFIG, SENSEVOICE_CONFIG,
                    NOISE_REDUCTION_CONFIG)
from noise_reducer import NoiseReducer
from audit_logger import ASRAuditEntry

logger = logging.getLogger('audio')
_diag_logger: Optional[logging.Logger] = None
_diag_handler: Optional[logging.FileHandler] = None

def _init_diag_logger(output_dir='.'):
    global _diag_logger, _diag_handler
    diag_file = os.path.join(output_dir, f'audio_diag_{datetime.now().strftime("%Y%m%d_%H%M%S")}.jsonl')
    _diag_logger = logging.getLogger('audio.diag')
    _diag_logger.setLevel(logging.DEBUG)
    _diag_logger.propagate = False
    _diag_handler = logging.FileHandler(diag_file, encoding='utf-8')
    _diag_handler.setLevel(logging.DEBUG)
    _diag_handler.setFormatter(logging.Formatter('%(message)s'))
    _diag_logger.addHandler(_diag_handler)
    return diag_file

def _diag(event_type, **kwargs):
    if _diag_logger is None: return
    r = {'ts': datetime.now().strftime('%H:%M:%S.%f')[:-3], 'event': event_type}
    r.update(kwargs)
    _diag_logger.info(json.dumps(r, ensure_ascii=False, default=str))

class AudioEngine(threading.Thread):
    _STEREO_MIX_KEYWORDS = ['立体声混音', 'stereo mix', '立体声', 'stereo', '映射器', 'mapper', '主声音', 'primary sound']

    def __init__(self, event_queue, stop_event, output_dir='.'):
        super().__init__(daemon=True)
        self._event_queue = event_queue
        self._stop_event = stop_event
        self._output_dir = output_dir
        self._automaton = None
        self._sensevoice_model = None
        self._sensevoice_available = False
        self._matched_in_current = set()
        self._current_text = ''
        self._last_result_count = 0
        self._latest_peak = 0.0
        self._audit_callback = None
        self._noise_reducer = None
        self._agc_peak = 200.0
        self._audio_buffer = []
        self._buffer_start_time = None
        self._noise_floor = 200.0
        self._noise_alpha = 0.98
        self._warmup_seconds = 4.0
        self._warmup_start = None
        self._warmed_up = False
        self._total_chunks = 0
        self._processed_audios = 0
        self._asr_calls = 0
        self._asr_errors = 0
        self._build_automaton()

    def _build_automaton(self):
        self._automaton = ahocorasick.Automaton()
        for w in FORBIDDEN_WORDS: self._automaton.add_word(w, w)
        self._automaton.make_automaton()

    def set_audit_callback(self, cb): self._audit_callback = cb
    def set_noise_reducer(self, nr): self._noise_reducer = nr

    def _is_stereo_mix(self, name):
        n = name.lower()
        return any(kw in n for kw in self._STEREO_MIX_KEYWORDS)

    def run(self):
        df = _init_diag_logger(self._output_dir)
        logger.info(f'diag: {df}')
        self._setup()
        if not self._sensevoice_available: return
        try: self._listen_loop()
        finally: self._cleanup()

    def _setup(self):
        os.environ.setdefault('FUNASR_DISABLE_TQDM', '1')
        os.environ.setdefault('TQDM_DISABLE', '1')
        try:
            from funasr import AutoModel
            self._f_am = AutoModel
        except ImportError:
            logger.error('funasr not installed'); return

        try:
            devs = sd.query_devices()
            ins = [d for d in devs if d['max_input_channels'] > 0]
            _diag('devs', n=len(ins), list=[{'i': d['index'], 'n': d['name']} for d in ins])
            for d in ins:
                tag = ' [STEREO_MIX!]' if self._is_stereo_mix(d['name']) else ''
                logger.info(f'  [{d["index"]}] {d["name"]}{tag}')
            self._device_index = AUDIO_CONFIG.get('device_index')
            if self._device_index is None:
                real = [d for d in ins if not self._is_stereo_mix(d['name'])]
                self._device_index = real[0]['index'] if real else None
                if real: print(f'[Audio] 自动选麦: [{self._device_index}] {real[0]["name"]}')
        except Exception as e:
            logger.warning(f'dev err: {e}')
            self._device_index = None

        print('[Audio] 加载模型...')
        try:
            self._sensevoice_model = self._f_am(
                model=SENSEVOICE_CONFIG['model'], vad_model=SENSEVOICE_CONFIG['vad_model'],
                vad_kwargs={'max_single_segment_time': SENSEVOICE_CONFIG['vad_max_segment'],
                            'speech_noise_thres': 0.3, 'min_silence_duration_ms': 200,
                            'min_speech_duration_ms': 100, 'max_speech_duration_s': 15},
                trust_remote_code=True, disable_update=True)
            self._sensevoice_available = True
            print('[Audio] 模型 OK')
        except Exception as e:
            logger.error(f'model err: {e}'); return

        self._sr = AUDIO_CONFIG['sample_rate']
        self._cs = AUDIO_CONFIG['chunk_size']
        self._gain = AUDIO_CONFIG.get('gain', 1.5)
        self._chunk_dur = SENSEVOICE_CONFIG['chunk_duration']

        if self._noise_reducer is None:
            self._noise_reducer = NoiseReducer(
                sample_rate=self._sr, n_fft=NOISE_REDUCTION_CONFIG['n_fft'],
                hop_length=NOISE_REDUCTION_CONFIG['hop_length'],
                noise_reduce_db=NOISE_REDUCTION_CONFIG['noise_reduce_db'],
                noise_smooth_frames=NOISE_REDUCTION_CONFIG['noise_smooth_frames'],
                learning_rate=NOISE_REDUCTION_CONFIG['learning_rate'],
                enabled=NOISE_REDUCTION_CONFIG['enabled'])

        nr_s = 'on' if self._noise_reducer.enabled else 'off'
        print(f'[Audio] sr={self._sr} buf={self._chunk_dur}s NR={nr_s}')
        _diag('ready', sr=self._sr, buf=self._chunk_dur, nr=nr_s, nf_init=self._noise_floor)

    def _listen_loop(self):
        sil = 0; max_sil = 30; last_diag = time.time()
        while not self._stop_event.is_set():
            try:
                chunk = sd.rec(self._cs, samplerate=self._sr, channels=1, dtype='int16',
                              device=self._device_index, blocking=True)
                c = chunk.flatten().astype(np.float64)
                self._total_chunks += 1
                pk = float(abs(c).max())
                self._latest_peak = pk

                if not self._warmed_up:
                    if self._warmup_start is None: self._warmup_start = time.time()
                    self._noise_floor = self._noise_alpha * self._noise_floor + (1 - self._noise_alpha) * pk
                    if time.time() - self._warmup_start >= self._warmup_seconds:
                        self._warmed_up = True
                        print(f'[Audio] warmup done, nf={self._noise_floor:.0f}')
                    continue

                if pk < self._noise_floor * 1.3:
                    self._noise_floor = self._noise_alpha * self._noise_floor + (1 - self._noise_alpha) * pk

                gate = max(200.0, self._noise_floor * 2.0)

                if time.time() - last_diag > 10:
                    _diag('hb', ch=self._total_chunks, pr=self._processed_audios,
                          asr=self._asr_calls, err=self._asr_errors, buf=len(self._audio_buffer),
                          nf=round(self._noise_floor, 0), gate=round(gate, 0))
                    last_diag = time.time()

                if pk < gate:
                    sil += 1
                    if self._audio_buffer and sil >= max_sil:
                        self._process_audio_buffer()
                        self._processed_audios += 1
                        sil = 0
                    continue

                if sil > 0: _diag('spk', pk=round(pk, 0), gate=round(gate, 0), sil=sil)
                sil = 0

                # AGC: gentle gain with hard clip, no tanh distortion
                self._agc_peak = 0.95 * self._agc_peak + 0.05 * pk
                tgt = max(2000.0, self._agc_peak * 2)
                dg = min(self._gain * 2, tgt / max(pk, 1))
                dg = max(0.8, min(4.0, dg))
                c = c * dg
                c = np.clip(c, -30000, 30000).astype(np.int16)

                if self._buffer_start_time is None: self._buffer_start_time = time.time()
                self._audio_buffer.append(c)

                if time.time() - self._buffer_start_time >= self._chunk_dur:
                    self._process_audio_buffer()
                    self._processed_audios += 1

            except Exception as e:
                logger.error(f'loop: {e}')
                if not self._stop_event.is_set(): time.sleep(0.1)

        if self._audio_buffer: self._process_audio_buffer()

    def _process_audio_buffer(self):
        t0 = time.perf_counter()
        if not self._audio_buffer: self._buffer_start_time = None; return

        bl = len(self._audio_buffer)
        try: audio = np.concatenate(self._audio_buffer)
        except Exception: self._audio_buffer = []; self._buffer_start_time = None; return

        dur = len(audio) / self._sr
        pk = float(abs(audio).max())
        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
        _diag('buf', n=bl, ms=round(dur * 1000, 0), pk=round(pk, 0), rms=round(rms, 0))

        # overlap: keep last 2.5s to avoid splitting speech mid-sentence
        on = int(2.5 * self._sr)
        self._audio_buffer = [audio[-on:].astype(np.int16)] if len(audio) > on else []
        self._buffer_start_time = None

        anom = []

        if len(audio) < self._sr * 0.3:
            anom.append('buf<0.3s')
            self._emit('', dur, rms, bl, '', ','.join(anom))
            return

        # denoise
        td = time.perf_counter()
        ad, dd = self._noise_reducer.process(audio)
        dn_ms = (time.perf_counter() - td) * 1000
        _diag('dn', db=dd['reduction_db'], ms=round(dn_ms, 1))
        dpk = float(abs(ad.astype(np.float64)).max())
        drms = float(np.sqrt(np.mean(ad.astype(np.float64) ** 2)))

        # pre-emphasis
        af = ad.astype(np.float32) / 32768.0
        af = np.append(af[0], af[1:] - 0.97 * af[:-1])

        if dur > 10: anom.append('buf>10s')
        if dpk < 100: anom.append('lo_pk')

        # ASR
        self._asr_calls += 1
        ta = time.perf_counter()
        try: result = self._sensevoice_model.generate(input=af, language='zh', use_itn=True)
        except Exception as e:
            self._asr_errors += 1
            anom.append('asr_err')
            self._emit('', dur, drms, bl, '', ','.join(anom))
            return
        asr_ms = (time.perf_counter() - ta) * 1000

        if not result or len(result) == 0:
            anom.append('empty')
            _diag('asr_none', ms=round(dur * 1000, 0), asr_ms=round(asr_ms, 0), pk=round(dpk, 0), rms=round(drms, 0))
            self._emit('', dur, drms, bl, '', ','.join(anom))
            return

        self._last_result_count = len(result)
        all_t = []; all_m = []; has = False

        for i, seg in enumerate(result):
            raw = seg.get('text', '').strip()
            if not raw: continue
            text = re.sub(r'<\|[^|]+\|>', '', raw).strip()
            text = re.sub(r'[<>【】\[\]]', '', text).strip()
            if text:
                self._current_text = text; has = True; all_t.append(text)
                print(f'\n  [识别] {text}')
                logger.info(f'  [{i}] "{text}"')
                all_m.extend(self._match(text))

        if not has: anom.append('empty')
        ct = ' | '.join(all_t) if all_t else ''
        cm = ', '.join(dict.fromkeys(all_m))
        total_ms = (time.perf_counter() - t0) * 1000
        _diag('asr', text=ct, matched=cm, segs=len(result), ms=round(dur * 1000, 0),
              asr_ms=round(asr_ms, 0), dn_ms=round(dn_ms, 1), total_ms=round(total_ms, 0),
              pk=round(dpk, 0), rms=round(drms, 0), anom=','.join(anom) if anom else '')
        self._emit(ct, dur, drms, bl, cm, ','.join(anom) if anom else '')

    def _emit(self, text, dur, pk, ch, matched, anom):
        if self._audit_callback:
            self._audit_callback(ASRAuditEntry(
                timestamp=datetime.now(), text=text, audio_duration_sec=round(dur, 2),
                audio_peak=round(pk, 0), buffer_chunks=ch, matched_words=matched,
                anomaly_flags=anom))

    def _match(self, text):
        mw = []; ms = []
        for ei, w in self._automaton.iter(text):
            if w not in self._matched_in_current: ms.append((ei, w)); self._matched_in_current.add(w)
        if ms:
            ws = [w for _, w in ms]; mw.extend(ws)
            logger.warning(f'hit: {ws}')
            for ei, w in ms:
                s = max(0, ei - len(w) - 15); e = min(len(text), ei + 15)
                self._event_queue.put(ViolationEvent(
                    timestamp=datetime.now(), violation_type='forbidden_word',
                    description=f'违禁词: {w}', context=text[s:e]))
            if len(self._matched_in_current) > 50: self._matched_in_current.clear()
        elif len(self._matched_in_current) > 10: self._matched_in_current.clear()



        return mw

    def _cleanup(self):
        self._audio_buffer = []

    def get_status(self):
        nr = self._noise_reducer.get_status() if self._noise_reducer else {}
        return {'sensevoice_available': self._sensevoice_available,
                'current_text': self._current_text,
                'buffer_chunks': len(self._audio_buffer),
                'last_result_count': self._last_result_count,
                'audio_peak': round(self._latest_peak, 0),
                'noise_floor': round(self._noise_floor, 1),
                'denoise_enabled': nr.get('enabled', False),
                'denoise_reduction_db': nr.get('last_reduction_db', 0)}
