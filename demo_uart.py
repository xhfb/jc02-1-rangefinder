#!/usr/bin/env python3
"""JC02-1 UART 调用示例"""

import sys

from jc02_1_uart import JC02LaserRangefinder

# Windows: COM3  Linux: /dev/ttyUSB0
PORT = "COM3" if sys.platform == "win32" else "/dev/ttyUSB0"

with JC02LaserRangefinder(PORT) as sensor:
    if sensor.wait_init():
        print("模组初始化完成")
    else:
        print("未收到 init ok，继续尝试测量...")

    # 单次测量
    print("\n--- 单次测量 ---")
    result = sensor.single_measure()
    print(f"距离: {result.distance_display}")
    print(f"角度: {result.angle_deg}°")
    print(f"速度: {result.speed_kmh} km/h")

    # 连续测量（读取 5 帧）
    print("\n--- 连续测量 (5 帧) ---")
    sensor.start_continuous()
    try:
        count = 0
        for measurement in sensor.iter_measurements(timeout=2.0):
            print(f"距离: {measurement.distance_display}  角度: {measurement.angle_deg}°")
            count += 1
            if count >= 5:
                break
    finally:
        sensor.stop_continuous()
