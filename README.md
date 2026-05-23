# JC02-1 激光测距模组 Python 驱动

JC02-1 激光测距模组的 Python 驱动，支持 **UART** 单次测量与连续测量。

## 功能

- 完整实现 JC02-1 串口通讯协议（帧同步、校验和、命令应答）
- 单次测量、连续测量、复位控制
- 解析距离、角度、速度等 19 字节测量数据域
- 上下文管理器（`with` 语句）自动管理串口生命周期

## 硬件

| 参数 | 说明 |
|------|------|
| 模组 | JC02-1 激光测距模组 |
| 接口 | UART（TTL 电平），默认 9600 8N1 |
| 供电 | +3.3V ~ +3.8V |
| 连接 | 模组 TX → 主机 RX，模组 RX → 主机 TX，共地 |

> 请将 Power ON 引脚拉高后再进行通讯。供电电压超出范围可能损坏模组。

## 安装

```bash
pip install pyserial
```

## 快速开始

### Python 调用

```python
from jc02_1_uart import JC02LaserRangefinder

with JC02LaserRangefinder("COM3") as sensor:  # Linux: /dev/ttyUSB0
    sensor.wait_init()
    result = sensor.single_measure()
    print(f"距离: {result.distance_display}")
    print(f"角度: {result.angle_deg}°")
```

```python
from jc02_1_uart import JC02LaserRangefinder

with JC02LaserRangefinder("COM3") as sensor:
    sensor.wait_init()
    sensor.start_continuous()
    try:
        for m in sensor.iter_measurements(timeout=2.0):
            print(m.distance_m, "m")
    finally:
        sensor.stop_continuous()
```

### 运行示例

```bash
python demo_uart.py
```

## API 参考

### 数据读取

| 方法 | 返回值 | 说明 |
|------|--------|------|
| `wait_init()` | `bool` | 等待上电 `init ok` 信息 |
| `single_measure()` | `MeasurementResult` | 单次测量 |
| `read_measurement_frame()` | `MeasurementResult \| None` | 连续模式下读取一帧 |
| `iter_measurements()` | 迭代器 | 连续测量数据流 |

### 控制

| 方法 | 说明 |
|------|------|
| `start_continuous()` | 启动连续测量 |
| `stop_continuous()` | 停止连续测量 |
| `reset()` | 复位模组 |

### MeasurementResult 字段

| 字段 | 单位 | 说明 |
|------|------|------|
| `distance_m` | 米 | 距离（已换算） |
| `angle_deg` | ° | 角度 |
| `horizontal_angle_deg` | ° | 水平角 |
| `elevation_angle_deg` | ° | 高低角 |
| `direction_angle_deg` | ° | 方向角 |
| `speed_kmh` | km/h | 速度 |
| `distance_display` | — | 格式化距离字符串 |

## 通讯协议摘要

- **帧格式**：`AE A7 | 长度 | 地址 | 命令 | 数据 | 校验和 | BC BE`
- **校验和**：`(长度 + 地址 + 命令 + sum(数据)) & 0xFF`
- **命令字**：复位 `0x0B`、单次测量 `0x05`、连续启动 `0x0E`、连续停止 `0x0F`

详细协议请参阅 `JC02-1 激光测距模组说明书.md`。

## 异常处理

```python
from jc02_1_uart import JC02LaserRangefinder, JC02TimeoutError, JC02ProtocolError

try:
    with JC02LaserRangefinder("COM3") as sensor:
        result = sensor.single_measure()
except JC02TimeoutError:
    print("等待应答或测量数据超时")
except JC02ProtocolError:
    print("帧校验或数据解析失败")
```

## 文件结构

```
jc02-1-rangefinder/
├── jc02_1_uart.py     # UART 驱动
├── demo_uart.py       # UART 调用示例
├── README.md
└── JC02-1 激光测距模组说明书.md
```

## License

MIT
