import numpy as np
from unittest.mock import MagicMock
from transcription.whisper_engine import WhisperTranscriber

def test_transcribe_chunk_output_language():
    """Verify that output_language='en' uses detect_language and dynamically sets task."""
    transcriber = WhisperTranscriber("tiny", "cpu", "int8")
    transcriber._model = MagicMock()
    
    samples = np.zeros(16000, dtype=np.float32)
    transcriber._model.transcribe.return_value = ([], None)

    # 1. Non-English speech + output_language="en" => "translate"
    transcriber._model.detect_language.return_value = ("hi", 0.9, [])
    transcriber.transcribe_chunk(samples, 16000, output_language="en")
    
    transcriber._model.transcribe.assert_called_with(
        samples,
        language="hi",
        task="translate",
        vad_filter=True,
        beam_size=5
    )
    
    # 2. English speech + output_language="en" => "transcribe"
    transcriber._model.detect_language.return_value = ("en", 0.9, [])
    transcriber.transcribe_chunk(samples, 16000, output_language="en")
    
    transcriber._model.transcribe.assert_called_with(
        samples,
        language="en",
        task="transcribe",
        vad_filter=True,
        beam_size=5
    )

    # 3. Non-English speech + output_language="hi" => "transcribe"
    transcriber._model.detect_language.return_value = ("hi", 0.9, [])
    transcriber.transcribe_chunk(samples, 16000, output_language="hi")
    
    transcriber._model.transcribe.assert_called_with(
        samples,
        language="hi",
        task="transcribe",
        vad_filter=True,
        beam_size=5
    )
