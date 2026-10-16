"""Giao diện broker adapter. CHỈ CÓ PHƯƠNG THỨC ĐỌC.

Thiếu hẳn các phương thức đặt, sửa, hủy lệnh hay chuyển tiền trong giao diện này là chủ đích:
dự án là công cụ quản trị rủi ro read-only. Test `test_readonly.py` kiểm tra điều này."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from ..models import (
    BoardQuote,
    Account,
    Candle,
    CashBalance,
    Interval,
    Loan,
    MarginBucket,
    Position,
    Quote,
    SessionInfo,
)


class BrokerError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.status = status


class AuthRequired(BrokerError):
    """Phiên hết hạn hoặc chưa đăng nhập, cần nhập OTP."""


def parse_guard(fn):
    """Biến lỗi đọc cấu trúc phản hồi (khác với tài liệu) thành BrokerError có nội dung rõ ràng, thay vì lỗi 500."""
    import functools

    @functools.wraps(fn)
    async def wrapper(self, *a, **kw):
        try:
            return await fn(self, *a, **kw)
        except BrokerError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError, IndexError) as e:
            raise BrokerError(
                f"{self.display_name}: phản hồi của {fn.__name__} không đúng cấu trúc dự kiến ({type(e).__name__}: {e}). "
                "Cấu trúc thật của API có thể khác tài liệu, cần chỉnh adapter."
            ) from e
    return wrapper


class ReadOnlyViolation(RuntimeError):
    """Cố gọi một request không phải đọc dữ liệu."""


class ReadOnlyHttp:
    """HTTP client chỉ cho phép GET. Có đúng một ngoại lệ có tên rõ ràng: POST lấy token
    đến những đường dẫn nằm trong danh sách cho phép (đăng nhập, không phải giao dịch)."""

    def __init__(
        self,
        base_url: str,
        *,
        auth_post_allowlist: frozenset[str] = frozenset(),
        timeout: float = 20.0,
    ):
        self._allow = auth_post_allowlist
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def get(self, path: str, params: dict[str, Any] | None = None,
                  headers: dict[str, str] | None = None) -> Any:
        try:
            r = await self._client.get(path, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise BrokerError(f"Không kết nối được {path}: {e}") from e
        return self._parse(r, path)

    async def auth_post(self, path: str, json: dict[str, Any],
                        headers: dict[str, str] | None = None) -> Any:
        if path not in self._allow:
            raise ReadOnlyViolation(f"POST {path} không nằm trong danh sách đăng nhập được phép")
        try:
            r = await self._client.post(path, json=json, headers=headers)
        except httpx.HTTPError as e:
            raise BrokerError(f"Không kết nối được {path}: {e}") from e
        return self._parse(r, path)

    @staticmethod
    def _parse(r: httpx.Response, path: str) -> Any:
        if r.status_code in (401, 403):
            raise AuthRequired(f"{path}: HTTP {r.status_code}, cần đăng nhập lại", r.status_code)
        if r.status_code >= 400:
            raise BrokerError(f"{path}: HTTP {r.status_code} {r.text[:200]}", r.status_code)
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError as e:
            raise BrokerError(f"{path}: phản hồi không phải JSON") from e

    async def aclose(self) -> None:
        await self._client.aclose()


class BrokerAdapter(ABC):
    name: str
    display_name: str
    short_name: str = ""   # nhãn nguồn dữ liệu ngắn gọn: TCBS, DNSE

    @abstractmethod
    def session_info(self) -> SessionInfo: ...

    async def authenticate(self, otp: str | None) -> SessionInfo:
        return self.session_info()

    @abstractmethod
    async def list_accounts(self) -> list[Account]: ...

    @abstractmethod
    async def get_positions(self, account_id: str) -> list[Position]: ...

    @abstractmethod
    async def get_cash(self, account_id: str) -> CashBalance: ...

    @abstractmethod
    async def get_margin(self, account_id: str, positions: list[Position]) -> list[MarginBucket]: ...

    @abstractmethod
    async def get_loans(self, account_id: str) -> list[Loan]: ...

    @abstractmethod
    async def get_candles(self, symbol: str, interval: Interval, count: int,
                          *, is_index: bool = False) -> list[Candle]: ...

    @abstractmethod
    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]: ...

    async def get_board(self, symbols: list[str]) -> dict[str, BoardQuote]:
        """Dữ liệu bảng giá. Mặc định chỉ có giá khớp; broker có đủ dữ liệu thì ghi đè."""
        q = await self.get_quotes(symbols)
        return {s: BoardQuote(symbol=s, price=v.price, ref=v.ref_price, change_pct=v.change_pct,
                              change=(v.price - v.ref_price) if v.price and v.ref_price else None)
                for s, v in q.items()}

    async def aclose(self) -> None:
        return None
