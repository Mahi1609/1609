# hf_summarizer.py
from transformers import pipeline
import threading

# Global summarizer variable
_SUMMARIZER = None
_LOCK = threading.Lock()

def get_summarizer():
    """
    Lazily load the summarizer pipeline so workers don't re-download repeatedly.
    """
    global _SUMMARIZER
    if _SUMMARIZER is None:
        with _LOCK:
            if _SUMMARIZER is None:
                # model choice: distilbart-cnn-12-6 is small and works well for summaries
                _SUMMARIZER = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6", device=-1)
    return _SUMMARIZER

def summarize_text(text: str, max_length: int = 120, min_length: int = 30):
    """
    Summarize given text and return a string. Wrap in try/except and fallback
    to a short extractive summary if HF summarizer fails.
    """
    if not text:
        return ""
    try:
        summarizer = get_summarizer()
        # Transformers pipeline expects reasonably sized chunks — limit input if too large
        input_text = text
        if len(input_text) > 4000:
            input_text = input_text[:4000]  # cut to 4000 chars to avoid token excess
        out = summarizer(input_text, max_length=max_length, min_length=min_length, do_sample=False)
        if isinstance(out, list) and len(out) > 0:
            return out[0].get("summary_text", "").strip()
        return ""
    except Exception as e:
        # fallback to a naive summary
        try:
            import re
            sentences = re.split(r'(?<=[.!?])\s+', text)
            return " ".join(sentences[:2])[:400]
        except Exception:
            return text[:400]
