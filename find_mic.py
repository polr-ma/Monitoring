# find_mic.py - 查找麦克风设备
import sounddevice as sd

print("=" * 60)
print("可用音频设备列表:")
print("=" * 60)

devices = sd.query_devices()
for i, device in enumerate(devices):
    print(f"\n设备 [{i}]:")
    print(f"  名称: {device['name']}")
    print(f"  输入通道: {device['max_input_channels']}")
    print(f"  输出通道: {device['max_output_channels']}")
    print(f"  默认采样率: {int(device['default_samplerate'])}Hz")

    if device['max_input_channels'] > 0:
        print(f"  ✅ 可用作麦克风")

print("\n" + "=" * 60)
print(f"当前默认输入设备: {sd.default.device[0]}")
print(f"当前默认输出设备: {sd.default.device[1]}")