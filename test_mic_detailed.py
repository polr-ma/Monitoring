# test_mic_detailed.py - 详细测试麦克风
import sounddevice as sd
import numpy as np
import wave


def test_specific_mic(device_index, device_name):
    print(f"\n测试设备 [{device_index}]: {device_name}")
    print("-" * 60)

    # 测试 16000Hz（与您的程序一致）
    sample_rate = 16000
    duration = 3

    print(f"采样率: {sample_rate}Hz, 时长: {duration}秒")
    print("3秒后开始录音，请正常说话...")

    for i in range(3, 0, -1):
        print(f"{i}...")
        sd.sleep(1000)

    print("🎤 录音中...")

    try:
        audio = sd.rec(
            int(duration * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype='int16',
            device=device_index,
        )
        sd.wait()

        audio_1d = audio.flatten()
        peak = np.abs(audio_1d).max()
        rms = np.sqrt(np.mean(audio_1d.astype(np.float64) ** 2))

        print(f"\n录音结果:")
        print(f"  峰值: {peak}")
        print(f"  RMS: {rms:.0f}")

        if peak < 500:
            print("  ⚠️ 音量太小！可能麦克风静音或未插入")
        elif peak < 2000:
            print("  ⚠️ 音量偏低，可能需要提高增益或在系统设置中调高麦克风音量")
        elif peak < 8000:
            print("  ✅ 音量适中")
        else:
            print("  ✅ 音量充足（注意避免削波）")

        # 保存测试音频
        filename = f'test_mic_device_{device_index}.wav'
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio.tobytes())
        print(f"测试音频已保存到: {filename}")

        return peak, rms

    except Exception as e:
        print(f"❌ 设备 [{device_index}] 测试失败: {e}")
        return 0, 0


# 测试几个可能的麦克风设备
mic_devices = [1, 5, 9, 10]  # 这些都是麦克风设备

results = {}
for device_id in mic_devices:
    peak, rms = test_specific_mic(device_id, f"麦克风 {device_id}")
    results[device_id] = (peak, rms)
    print()

print("=" * 60)
print("测试总结:")
print("=" * 60)
for device_id, (peak, rms) in results.items():
    status = "✅" if peak > 2000 else "⚠️"
    print(f"{status} 设备 [{device_id}]: 峰值={peak:.0f}, RMS={rms:.0f}")

best_device = max(results.items(), key=lambda x: x[1][0])
print(f"\n推荐使用设备 [{best_device[0]}]，峰值最高: {best_device[1][0]:.0f}")