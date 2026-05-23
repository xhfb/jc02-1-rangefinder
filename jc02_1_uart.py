#!/usr/bin/env python3
"""JC02-1 激光测距模组 UART 驱动 (Python)

协议依据《JC02-1 激光测距模组说明书》：
- 默认波特率 9600，8N1
- 帧格式：AE A7 | 长度 | 地址 | 命令 | 数据 | 校验和 | BC BE
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import BinaryIO, Iterator, Optional, Union

try:
    import serial
except ImportError:  # pragma: no cover
    serial = None  # type: ignore


# 帧常量
_HEADER = bytes((0xAE, 0xA7))
_FOOTER = bytes((0xBC, 0xBE))
_INIT_MESSAGE = b"init ok\r\n"

# 命令字
CMD_RESET = 0x0B
CMD_SINGLE_MEASURE = 0x05
CMD_CONTINUOUS_START = 0x0E
CMD_CONTINUOUS_STOP = 0x0F

# 应答命令字（命令字 | 0x80）
RESP_RESET = 0x8B
RESP_SINGLE = 0x85
RESP_CONTINUOUS_START = 0x8E
RESP_CONTINUOUS_STOP = 0x8F

# 距离单位
UNIT_DISTANCE_0_1M = 0x00
UNIT_DISTANCE_0_1KM = 0x02

# 单次测量数据域长度（9×int16 + 1 字节单位）
_MEASUREMENT_DATA_LEN = 19


class JC02Error(Exception):
    """JC02-1 驱动基础异常。"""


class JC02ProtocolError(JC02Error):
    """协议解析或校验失败。"""


class JC02TimeoutError(JC02Error):
    """等待应答或测量数据超时。"""


@dataclass(frozen=True)
class MeasurementResult:
    """单次/连续测量解析结果。"""

    angle_deg: float
    """角度，单位 °（原始值 × 0.1）。"""
    distance_m: float
    """距离，已换算为米。"""
    positive_error: int
    """正误差（原始有符号值）。"""
    horizontal_angle_deg: float
    """水平角，单位 °。"""
    elevation_angle_deg: float
    """高低角，单位 °。"""
    direction_angle_deg: float
    """方向角，单位 °。"""
    horizontal_included_angle_deg: float
    """水平夹角，单位 °。"""
    span: int
    """跨距（原始有符号值）。"""
    speed_kmh: float
    """速度，单位 km/h（原始值 × 0.1）。"""
    distance_unit: int
    """距离单位字节：0x00=0.1m，0x02=0.1km。"""

    @property
    def distance_display(self) -> str:
        """按模组单位规则格式化的距离字符串。"""
        if self.distance_unit == UNIT_DISTANCE_0_1KM:
            return f"{self.distance_m / 1000:.3f} km"
        return f"{self.distance_m:.1f} m"


def _checksum(length: int, address: int, command: int, data: bytes) -> int:
    return (length + address + command + sum(data)) & 0xFF


def build_frame(address: int, command: int, data: bytes = b"") -> bytes:
    """构造符合协议的数据帧。"""
    length = 4 + len(data)
    cs = _checksum(length, address, command, data)
    return _HEADER + bytes((length, address, command)) + data + bytes((cs,)) + _FOOTER


def _signed_short_be(buf: bytes, offset: int) -> int:
    return struct.unpack_from(">h", buf, offset)[0]


def parse_measurement_payload(data: bytes) -> MeasurementResult:
    """解析测量数据域（19 字节）。"""
    if len(data) < _MEASUREMENT_DATA_LEN:
        raise JC02ProtocolError(
            f"测量数据域长度不足：期望 {_MEASUREMENT_DATA_LEN} 字节，实际 {len(data)} 字节"
        )

    angle_raw = _signed_short_be(data, 0)
    distance_raw = _signed_short_be(data, 2)
    positive_error = _signed_short_be(data, 4)
    h_angle_raw = _signed_short_be(data, 6)
    elev_raw = _signed_short_be(data, 8)
    dir_raw = _signed_short_be(data, 10)
    h_incl_raw = _signed_short_be(data, 12)
    span = _signed_short_be(data, 14)
    speed_raw = _signed_short_be(data, 16)
    unit = data[18]

    if unit == UNIT_DISTANCE_0_1KM:
        distance_m = distance_raw * 100.0
    else:
        distance_m = distance_raw * 0.1

    return MeasurementResult(
        angle_deg=angle_raw * 0.1,
        distance_m=distance_m,
        positive_error=positive_error,
        horizontal_angle_deg=h_angle_raw * 0.1,
        elevation_angle_deg=elev_raw * 0.1,
        direction_angle_deg=dir_raw * 0.1,
        horizontal_included_angle_deg=h_incl_raw * 0.1,
        span=span,
        speed_kmh=speed_raw * 0.1,
        distance_unit=unit,
    )


@dataclass
class _ParsedFrame:
    length: int
    address: int
    command: int
    data: bytes
    checksum: int


class _FrameParser:
    """从串口流中同步并提取完整协议帧。"""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[_ParsedFrame]:
        self._buf.extend(chunk)
        frames: list[_ParsedFrame] = []
        while True:
            frame = self._try_extract_one()
            if frame is None:
                break
            frames.append(frame)
        return frames

    def _try_extract_one(self) -> Optional[_ParsedFrame]:
        buf = self._buf
        start = buf.find(_HEADER)
        if start < 0:
            if len(buf) > 1:
                del buf[:-1]
            return None
        if start > 0:
            del buf[:start]

        if len(buf) < 5:
            return None

        length = buf[2]
        if length < 4:
            del buf[0:1]
            return None

        total = 2 + length + 2
        if len(buf) < total:
            return None

        if buf[total - 2 : total] != _FOOTER:
            del buf[0:1]
            return None

        address = buf[3]
        command = buf[4]
        data_end = total - 3
        data = bytes(buf[5:data_end])
        checksum = buf[data_end]
        expected = _checksum(length, address, command, data)
        if checksum != expected:
            del buf[0:1]
            raise JC02ProtocolError(
                f"校验和错误：期望 0x{expected:02X}，收到 0x{checksum:02X}"
            )

        frame = _ParsedFrame(
            length=length,
            address=address,
            command=command,
            data=data,
            checksum=checksum,
        )
        del buf[:total]
        return frame


class JC02LaserRangefinder:
    """
    JC02-1 激光测距模组通讯类。

    示例::

        from jc02_1_uart import JC02LaserRangefinder

        with JC02LaserRangefinder("COM3") as sensor:
            sensor.wait_init()
            result = sensor.single_measure()
            print(result.distance_m, "m")
    """

    def __init__(
        self,
        port: str,
        *,
        baudrate: int = 9600,
        address: int = 0x00,
        timeout: float = 1.5,
    ) -> None:
        if serial is None:
            raise ImportError("请先安装 pyserial：pip install pyserial")

        self.port = port
        self.baudrate = baudrate
        self.address = address & 0xFF
        self.timeout = timeout
        self._ser: Optional[serial.Serial] = None
        self._parser = _FrameParser()

    def __enter__(self) -> JC02LaserRangefinder:
        self.open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def open(self) -> None:
        """打开串口。"""
        if self.is_open:
            return
        self._ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
        )
        self._parser = _FrameParser()
        self._ser.reset_input_buffer()

    def close(self) -> None:
        """关闭串口。"""
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    def _require_serial(self) -> serial.Serial:
        if not self.is_open or self._ser is None:
            raise JC02Error("串口未打开，请先调用 open() 或使用 with 语句")
        return self._ser

    def _write(self, frame: bytes) -> None:
        ser = self._require_serial()
        ser.write(frame)
        ser.flush()

    def _read_available(self) -> bytes:
        ser = self._require_serial()
        n = ser.in_waiting
        if n <= 0:
            chunk = ser.read(1)
            return chunk if chunk else b""
        return ser.read(n)

    def _collect_frames(self, deadline: float) -> list[_ParsedFrame]:
        frames: list[_ParsedFrame] = []
        while time.monotonic() < deadline:
            chunk = self._read_available()
            if chunk:
                frames.extend(self._parser.feed(chunk))
                if frames:
                    return frames
            else:
                time.sleep(0.01)
        return frames

    def _send_command(
        self,
        command: int,
        data: bytes = b"",
        *,
        expect_command: Optional[int] = None,
        expect_data_len: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> _ParsedFrame:
        frame = build_frame(self.address, command, data)
        self._write(frame)
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while time.monotonic() < deadline:
            for parsed in self._collect_frames(deadline):
                if parsed.address != self.address:
                    continue
                if expect_command is not None and parsed.command != expect_command:
                    continue
                if expect_data_len is not None and len(parsed.data) != expect_data_len:
                    continue
                return parsed
        raise JC02TimeoutError(
            f"等待命令 0x{command:02X} 应答超时（{timeout or self.timeout}s）"
        )

    def drain(self) -> None:
        """清空接收缓冲区及内部帧解析状态。"""
        ser = self._require_serial()
        ser.reset_input_buffer()
        self._parser = _FrameParser()

    def wait_init(self, timeout: Optional[float] = None) -> bool:
        """
        等待上电初始化信息 ``init ok\\r\\n``。

        Returns:
            是否在超时前收到初始化信息。
        """
        ser = self._require_serial()
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = self._read_available()
            if chunk:
                buf.extend(chunk)
                if _INIT_MESSAGE in buf:
                    return True
            else:
                time.sleep(0.01)
        return False

    def reset(self, timeout: Optional[float] = None) -> None:
        """复位控制。"""
        self._send_command(
            CMD_RESET,
            b"\x00",
            expect_command=RESP_RESET,
            timeout=timeout,
        )

    def single_measure(self, timeout: Optional[float] = None) -> MeasurementResult:
        """
        启动单次测量并返回解析结果。

        模组先返回简短应答，再返回带 19 字节数据域的测量包（命令字 0x85）。
        说明书标注最大测量时间 ≤0.9s，默认超时 1.5s。
        """
        measure_timeout = timeout if timeout is not None else max(self.timeout, 1.5)
        self._send_command(CMD_SINGLE_MEASURE, expect_command=RESP_SINGLE, timeout=2.0)

        deadline = time.monotonic() + measure_timeout
        while time.monotonic() < deadline:
            for parsed in self._collect_frames(deadline):
                if parsed.address != self.address:
                    continue
                if parsed.command != RESP_SINGLE:
                    continue
                if len(parsed.data) >= _MEASUREMENT_DATA_LEN:
                    return parse_measurement_payload(parsed.data)
            time.sleep(0.01)

        raise JC02TimeoutError(f"等待单次测量数据超时（{measure_timeout}s）")

    def start_continuous(self, timeout: Optional[float] = None) -> None:
        """启动连续测量。"""
        self._send_command(
            CMD_CONTINUOUS_START,
            expect_command=RESP_CONTINUOUS_START,
            timeout=timeout,
        )

    def stop_continuous(self, timeout: Optional[float] = None) -> None:
        """停止连续测量。"""
        self._send_command(
            CMD_CONTINUOUS_STOP,
            expect_command=RESP_CONTINUOUS_STOP,
            timeout=timeout,
        )

    def read_measurement_frame(
        self, timeout: Optional[float] = None
    ) -> Optional[MeasurementResult]:
        """
        在连续测量模式下读取一帧测量数据。

        Returns:
            解析成功返回 MeasurementResult，超时返回 None。
        """
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while time.monotonic() < deadline:
            for parsed in self._collect_frames(deadline):
                if parsed.address != self.address:
                    continue
                if parsed.command == RESP_SINGLE and len(parsed.data) >= _MEASUREMENT_DATA_LEN:
                    return parse_measurement_payload(parsed.data)
            time.sleep(0.01)
        return None

    def iter_measurements(self, timeout: Optional[float] = None) -> Iterator[MeasurementResult]:
        """
        连续测量数据迭代器；需先调用 start_continuous()。

        Args:
            timeout: 每帧等待超时，None 表示使用实例默认 timeout。
        """
        while True:
            result = self.read_measurement_frame(timeout=timeout)
            if result is None:
                break
            yield result


# 便于测试/调试：预置命令帧
PRESET_FRAMES = {
    "reset": build_frame(0x00, CMD_RESET, b"\x00"),
    "single_measure": build_frame(0x00, CMD_SINGLE_MEASURE),
    "continuous_start": build_frame(0x00, CMD_CONTINUOUS_START),
    "continuous_stop": build_frame(0x00, CMD_CONTINUOUS_STOP),
}
