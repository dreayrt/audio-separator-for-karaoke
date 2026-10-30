import numpy as np
import soundfile as sf
from audio_separator.separator.audio_chunking import AudioChunker


def test_wav_split_merge_preserves_last_fraction_of_millisecond(tmp_path):
    # This length cannot be represented by an integer number of milliseconds at 44.1 kHz.
    frames = 123457
    source = tmp_path / 'source.wav'
    signal = np.random.default_rng(7).integers(-20000, 20000, (frames, 2), dtype=np.int16)
    sf.write(source, signal, 44100, subtype='PCM_16')
    chunker = AudioChunker(.4)
    chunks = chunker.split_audio(str(source), str(tmp_path / 'chunks'))
    output = tmp_path / 'merged.wav'
    chunker.merge_chunks(chunks, str(output))
    result, rate = sf.read(output, dtype='int16', always_2d=True)
    assert rate == 44100
    assert len(result) == frames
    np.testing.assert_array_equal(result, signal)
