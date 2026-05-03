from abc import ABC, abstractmethod


class BaseTTSEngine(ABC):
    @abstractmethod
    def list_voices(self) -> list[dict]:
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        pass

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: str,
        speed: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> bool:
        pass

    @property
    @abstractmethod
    def engine_name(self) -> str:
        pass
