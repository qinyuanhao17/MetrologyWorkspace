"""Create explicitly synthetic rigid wavelength shifts from verified SE3.3 SME files."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metrology_app.sme_spectra import SMEReader, load_folder, parse_sme_file, read_channel_header


def shifted_bytes(raw, wafer, lot, offset):
    payload = base64.b64decode(raw[3:].strip(), validate=True)
    reader = SMEReader(payload)
    if reader.qstring() != "SE3.3" or reader.u32() != 1:
        raise ValueError("This generator only patches the verified single-channel SE3.3 layout")
    name_start = reader.pos
    name = reader.qstring()
    name_end = reader.pos
    tokens = name.split("_")
    if len(tokens) < 4:
        raise ValueError("Missing verified embedded source identity")
    tokens[:2] = [wafer, lot]
    new_name = "_".join(tokens).encode("utf-16be")
    read_channel_header(reader)
    zero = reader.f64_array("zero_channel")
    count = reader.u32()
    if count != len(zero):
        raise ValueError("Unexpected wavelength layout")
    wave_start = reader.pos
    wave = np.frombuffer(reader.take(count * 8), dtype=">f8").astype(float) + offset
    if not np.isfinite(wave).all() or not (np.diff(wave) > 0).all() or wave.min() <= 0:
        raise ValueError("Invalid shifted wavelength coordinates")
    patched = bytearray(payload)
    patched[wave_start:reader.pos] = wave.astype(">f8").tobytes()
    patched[name_start:name_end] = struct.pack(">I", len(new_name)) + new_name
    return b"SE3" + base64.b64encode(patched)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--shift-nm", type=float, default=20.0)
    args = parser.parse_args()
    if not np.isfinite(args.shift_nm) or args.shift_nm <= 0:
        raise ValueError("shift-nm must be positive")
    source = load_folder(args.source)
    if not source.spectra or source.issues:
        raise ValueError(f"Use a completely readable source folder: {len(source.issues)} issues")
    args.output.mkdir(parents=True, exist_ok=False)
    cases = (("Red", "SYNRED.00-01", "SYNRED.01", args.shift_nm),
             ("Blue", "SYNBLUE.00-02", "SYNBLUE.02", -args.shift_nm))
    for folder, *_ in cases:
        (args.output / folder).mkdir()
    manifest = {"synthetic": True, "source_folder": str(args.source.resolve()),
                "method": "Rigid translation of wavelength coordinates; original ordinate values retained exactly; no resampling.",
                "groups": [{"folder": f, "wafer_id": w, "lot": l, "shift_nm": d} for f, w, l, d in cases],
                "files": []}
    for index, spectrum in enumerate(source.spectra, 1):
        raw = spectrum.path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        for folder, wafer, lot, offset in cases:
            target = args.output / folder / f"{folder.upper()}_{index:04d}.sme"
            content = shifted_bytes(raw, wafer, lot, offset)
            target.write_bytes(content)
            loaded = parse_sme_file(target)
            assert (loaded.identity.wafer, loaded.identity.lot) == (wafer, lot)
            assert (loaded.identity.die_seq, loaded.identity.pad, loaded.identity.tool_sn,
                    loaded.identity.timestamp, loaded.x_mm, loaded.y_mm) == (
                    spectrum.identity.die_seq, spectrum.identity.pad, spectrum.identity.tool_sn,
                    spectrum.identity.timestamp, spectrum.x_mm, spectrum.y_mm)
            assert len(loaded.channels) == len(spectrum.channels)
            for before, after in zip(spectrum.channels, loaded.channels):
                assert before.key == after.key
                np.testing.assert_array_equal(after.wavelength, before.wavelength + offset)
                np.testing.assert_array_equal(after.numeric[:, 1:], before.numeric[:, 1:])
            manifest["files"].append({"source": str(spectrum.path.relative_to(args.source)),
                "source_sha256": digest, "output": str(target.relative_to(args.output)),
                "output_sha256": hashlib.sha256(content).hexdigest(), "shift_nm": offset})
        assert hashlib.sha256(spectrum.path.read_bytes()).hexdigest() == digest
    manifest["files_per_group"] = len(source.spectra)
    manifest["verification"] = "Every output parsed successfully; identities, shifts, ordinates and coordinates verified; source hashes unchanged."
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (args.output / "README_SYNTHETIC.txt").write_text(
        "合成光谱，仅用于软件功能测试，不是真实量测结果。\n"
        f"红移 +{args.shift_nm:g} nm：Wafer SYNRED.00-01，Lot SYNRED.01。\n"
        f"蓝移 -{args.shift_nm:g} nm：Wafer SYNBLUE.00-02，Lot SYNBLUE.02。\n"
        f"每组 {len(source.spectra)} 个 SME 文件；修改了文件内部的 Wafer/Lot 身份。\n"
        "方法：平移波长轴，所有光谱纵坐标数值不变，不做插值。\n"
        "Die、坐标、角度及采集时间保留源文件内容；采集时间不是本次合成时间。\n"
        "软件 File → Load Spectra 选择本目录可同时读取两组，也可单独选择 Red 或 Blue。\n"
        "来源对应关系、偏移量和 SHA256 校验值见 manifest.json。\n", encoding="utf-8-sig")
    print(json.dumps({"output": str(args.output.resolve()), "files_per_group": len(source.spectra),
                      "total_sme": len(manifest["files"]), "groups": manifest["groups"]}))


if __name__ == "__main__":
    main()
