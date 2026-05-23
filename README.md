# JC02-1 激光测距模组 Python 驱动

基于 UART 通讯协议的 JC02-1 激光测距模组 Python 驱动库，支持单次测量与连续测量，适用于 Windows / Linux / macOS。

## 特性

- 完整实现 JC02-1 串口通讯协议（帧同步、校验和、命令应答）
- 支持单次测量、连续测量、复位控制
- 解析距离、角度、速度等 19 字节测量数据域
- 上下文管理器（`with` 语句）自动管理串口生命周期
- 类型注解，便于 IDE 提示

## 硬件要求

| 项目 | 说明 |
|------|------|
| 模组 | JC02-1 激光测距模组 |
| 接口 | UART（TTL 电平），默认 9600 8N1 |
| 供电 | +3.3V ~ +3.8V |
| 连接 | 模组 TX → 主机 RX，模组 RX → 主机 TX，共地 |

> 请将 Power ON 引脚拉高后再进行通讯。供电电压超出范围可能损坏模组。

## 安装

```bash
git clone https://github.com/xhfb/jc02-1-rangefinder.git
cd jc02-1-rangefinder
pip install -r requirements.txt
```

或直接将 `jc02_1` 目录复制到你的项目中，并安装依赖：

```bash
pip install pyserial>=3.5
```

## 快速开始

### 单次测量

```python
from jc02_1 import JC02LaserRangefinder

with JC02LaserRangefinder("COM3") as sensor:  # Linux 下通常为 /dev/ttyUSB0
    sensor.wait_init()          # 等待上电 "init ok" 信息
    result = sensor.single_measure()
    print(f"距离: {result.distance_display}")
    print(f"角度: {result.angle_deg}°")
    print(f"速度: {result.speed_kmh} km/h")
```

### 连续测量

```python
from jc02_1 import JC02LaserRangefinder

with JC02LaserRangefinder("COM3") as sensor:
    sensor.wait_init()
    sensor.start_continuous()
    try:
        for measurement in sensor.iter_measurements(timeout=2.0):
            print(measurement.distance_m, "m")
    finally:
        sensor.stop_continuous()
```

## API 概览

| 类 / 方法 | 说明 |
|-----------|------|
| `JC02LaserRangefinder(port, baudrate=9600, address=0x00, timeout=1.5)` | 主驱动类 |
| `wait_init()` | 等待模组上电初始化信息 |
| `single_measure()` | 单次测量，返回 `MeasurementResult` |
| `start_continuous()` / `stop_continuous()` | 启动 / 停止连续测量 |
| `iter_measurements()` | 连续测量数据迭代器 |
| `reset()` | 复位模组 |
| `MeasurementResult` | 测量结果数据类 |

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
- **应答命令字**：原命令字 \| `0x80`

详细协议请参阅仓库内 `JC02-1 激光测距模组说明书.md`。

## 异常处理

```python
from jc02_1 import JC02LaserRangefinder, JC02TimeoutError, JC02ProtocolError

try:
    with JC02LaserRangefinder("COM3") as sensor:
        result = sensor.single_measure()
except JC02TimeoutError:
    print("等待应答或测量数据超时")
except JC02ProtocolError:
    print("帧校验或数据解析失败")
```

## 项目结构

```
jc02-1-rangefinder/
├── jc02_1/
│   ├── __init__.py       # 包入口
│   └── rangefinder.py    # 驱动实现
├── requirements.txt
├── README.md
└── JC02-1 激光测距模组说明书.md
```

## 许可证

MIT License
