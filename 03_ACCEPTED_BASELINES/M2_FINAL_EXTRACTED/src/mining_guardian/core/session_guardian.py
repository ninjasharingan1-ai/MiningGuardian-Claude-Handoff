import uuid
from datetime import datetime

from ..logging import get_logger
from ..models import SessionRecord

logger = get_logger(__name__)


class SessionManager:
    def __init__(self) -> None:
        self.current_session: SessionRecord | None = None

    def create_session(
        self,
        algorithm: str | None = None,
        *,
        miner: str = "srbminer",
        gpu_ids: list[int] | None = None,
        payout_coin: str | None = None,
    ) -> SessionRecord:
        algorithm_ids = [] if algorithm in (None, "", "unknown") else [algorithm]
        self.current_session = SessionRecord(
            session_id=f"session_{uuid.uuid4().hex[:12]}",
            miner=miner,
            gpu_ids=gpu_ids or [],
            algorithm_ids=algorithm_ids,
            start_time=datetime.now(),
            payout_coin=payout_coin,
        )
        logger.info("session_created", session_id=self.current_session.session_id, miner=miner)
        return self.current_session

    def update_algorithms(self, algorithm_ids: list[str], raw_names: list[str]) -> None:
        if self.current_session is None:
            return
        self.current_session.algorithm_ids = list(dict.fromkeys(algorithm_ids))
        self.current_session.raw_algorithm_names = list(dict.fromkeys(raw_names))

    def get_current_session(self) -> SessionRecord | None:
        return self.current_session

    def end_session(self) -> None:
        if self.current_session is not None and self.current_session.end_time is None:
            self.current_session.end_time = datetime.now()
            logger.info("session_ended", session_id=self.current_session.session_id)
