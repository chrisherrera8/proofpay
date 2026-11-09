from app.config import get_settings
from app.vision.base import ImageInput, ItemResult, VisionError, VisionProvider, VisionResult
from app.vision.gemini import GeminiProvider

__all__ = ["ImageInput", "ItemResult", "VisionError", "VisionProvider", "VisionResult", "get_vision_provider"]


def get_vision_provider() -> VisionProvider:
    """FastAPI dependency. Tests override it with a fake."""
    s = get_settings()
    if not s.gemini_api_key:
        raise VisionError("GEMINI_API_KEY is not set")
    return GeminiProvider(s.gemini_api_key, s.gemini_model)
