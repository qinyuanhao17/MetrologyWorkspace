"""Read verified SME spectra and preserve their source identity.

Layouts are validated against supplied counted-array and compressed legacy
records. Instrument, mode and version are retained as metadata, not allowlists.
"""
from __future__ import annotations

import base64
import math
import os
import re
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np
from .file_paths import filesystem_path


M_COLS = [f"M{i}{j}" for i in range(4) for j in range(4)]
M_COL_INDEX = {name: 8 + index for index, name in enumerate(M_COLS)}
MAX_SPECTRAL_POINTS = 1_000_000
PARSER_VERSION = "3.2.0"
SPECTRUM_GROUP_FIELDS = {
    "wafer": ("wafer", "lot", "pad"),
    "lot": ("lot", "wafer", "pad"),
    "pad": ("pad", "wafer", "lot"),
    "die": ("die", "wafer", "lot", "pad"),
}
METADATA_COLUMNS = (
    "Wafer ID",
    "SME Name",
    "Lot ID",
    "Tool SN",
    "PAD Name",
    "Die Seq",
    "FIELD X",
    "FIELD Y",
    "Time",
    "Folder",
    "Instrument",
    "Mode",
    "Version",
    "Sample ID",
    "Channel Count",
    "Channel ID",
    "Metadata Parse Status",
    "Spectrum Parse Status",
    "Parse Error",
)

_DIE_PATTERN = re.compile(r"_Die(\d+)_(?:C(-?\d+)_R(-?\d+)|R(-?\d+)_C(-?\d+))", flags=re.I)
_FILENAME_TIMESTAMP_PATTERN = re.compile(r"(?<!\d)(\d{17})(?!\d)")


class UnsupportedSME(ValueError):
    """An SME layout that cannot be identified safely."""


class EncryptedSME(UnsupportedSME):
    """An encryption envelope rather than accessible spectral bytes."""


@dataclass(frozen=True, slots=True)
class FilenameMetadata:
    raw_filename: str
    wafer_id: str
    lot_id: str
    tool_sn: str
    pad_name: str
    die_seq: int | None
    field_x: int | None
    field_y: int | None
    time: str
    timestamp_raw: str
    parse_status: str


def _display_timestamp(raw: Any) -> str:
    text = str(raw or "").strip()
    if len(text) >= 14 and text[:14].isdigit():
        try:
            parsed = datetime.strptime(text[:14], "%Y%m%d%H%M%S")
        except ValueError:
            pass
        else:
            millis = text[14:17] if len(text) >= 17 and text[14:17].isdigit() else ""
            suffix = f".{millis}" if millis else ""
            return parsed.strftime("%Y-%m-%d %H:%M:%S") + suffix
    return text


def _die_fields(match):
    return int(match[1]), int(match[2] or match[5]), int(match[3] or match[4])


def parse_spectrum_filename(filename: str) -> FilenameMetadata:
    """Parse the internal SME naming convention without guessing unknown data."""
    raw = str(filename or "").strip()
    name = Path(raw).name
    die_match = _DIE_PATTERN.search(name)
    timestamp_matches = _FILENAME_TIMESTAMP_PATTERN.findall(name)
    timestamp_raw = timestamp_matches[-1] if timestamp_matches else ""
    if die_match is None:
        return FilenameMetadata(
            raw_filename=raw,
            wafer_id="",
            lot_id="",
            tool_sn="",
            pad_name="",
            die_seq=None,
            field_x=None,
            field_y=None,
            time=_display_timestamp(timestamp_raw),
            timestamp_raw=timestamp_raw,
            parse_status="unrecognized",
        )

    prefix = name[:die_match.start()].strip("_")
    die, field_x, field_y = _die_fields(die_match)
    tokens = [token for token in prefix.split("_") if token]
    if len(tokens) < 3:
        return FilenameMetadata(
            raw_filename=raw,
            wafer_id="",
            lot_id="",
            tool_sn="",
            pad_name="",
            die_seq=die,
            field_x=field_x,
            field_y=field_y,
            time=_display_timestamp(timestamp_raw),
            timestamp_raw=timestamp_raw,
            parse_status="partial",
        )

    candidate_pad = tokens[3] if len(tokens) >= 4 else ""
    return FilenameMetadata(
        raw_filename=raw,
        wafer_id=tokens[0],
        lot_id=tokens[1],
        tool_sn=tokens[2],
        pad_name=candidate_pad,
        die_seq=die,
        field_x=field_x,
        field_y=field_y,
        time=_display_timestamp(timestamp_raw),
        timestamp_raw=timestamp_raw,
        parse_status="ok" if timestamp_raw else "partial",
    )


class SMEReader:
    def __init__(self, payload: bytes):
        self.data = payload
        self.pos = 0

    def take(self, size: int) -> bytes:
        if size < 0 or self.pos + size > len(self.data):
            raise ValueError(f"Truncated SME at decoded byte {self.pos}, size {size}")
        result = self.data[self.pos:self.pos + size]
        self.pos += size
        return result

    def u32(self) -> int:
        return struct.unpack(">I", self.take(4))[0]

    def f64(self) -> float:
        return struct.unpack(">d", self.take(8))[0]

    def qstring(self) -> str:
        size = self.u32()
        if size > 32768 or size % 2:
            raise ValueError(f"Invalid UTF-16BE string byte count {size}")
        return self.take(size).decode("utf-16be")

    def f64_array(self, label: str, expected: int | None = None) -> np.ndarray:
        size = self.u32()
        if size > MAX_SPECTRAL_POINTS * 16:
            raise ValueError(f"{label}: unreasonable array length {size}")
        if expected is not None and size != expected:
            raise ValueError(f"{label}: length {size}, expected {expected}")
        return np.frombuffer(self.take(size * 8), dtype=">f8").astype(np.float64)


@dataclass(slots=True)
class ParsedChannel:
    metadata: dict[str, Any]
    numeric: np.ndarray
    spectrum_type: str


def read_channel_header(reader: SMEReader) -> dict[str, Any]:
    sample_type = reader.u32()
    sample_id = reader.qstring()
    instrument = reader.qstring()
    mode = reader.qstring()
    angles = [reader.f64() for _ in range(3)]
    label = reader.qstring()
    reserved = reader.take(32)
    scalar = reader.f64()
    coordinate_count = reader.u32()
    if coordinate_count > 32:
        raise ValueError(f"Unreasonable coordinate count {coordinate_count}")
    coordinates = [reader.f64() for _ in range(coordinate_count)]
    return {
        "sample_type": sample_type,
        "sample_id": sample_id,
        "instrument": instrument,
        "mode": mode,
        "angle_1_deg": angles[0],
        "angle_2_deg": angles[1],
        "angle_3_deg": angles[2],
        "header_label": label,
        "header_reserved_hex": reserved.hex(),
        "unknown_scalar": scalar,
        "coordinate_count": coordinate_count,
        "coord_x": coordinates[0] if coordinate_count >= 1 else None,
        "coord_y": coordinates[1] if coordinate_count >= 2 else None,
    }


def validate_wavelength(wavelength: np.ndarray, label: str) -> None:
    if (
        wavelength.size == 0
        or not np.isfinite(wavelength).all()
        or not np.all(np.diff(wavelength) > 0)
    ):
        raise ValueError(f"{label}: nonmonotonic / invalid wavelength array")


def base_metadata(
    path: Path,
    version: str,
    filename: str,
    channel_total: int,
    global_tag: int | None,
) -> dict[str, Any]:
    tags: dict[str, Any] = {}
    embedded = parse_spectrum_filename(filename)
    external = parse_spectrum_filename(path.name)

    def business_value(field: str) -> Any:
        value = getattr(embedded, field)
        return value if value not in (None, "") else getattr(external, field)

    def parse_value(field: str) -> Any:
        value = business_value(field)
        if field == "time":
            return _display_timestamp(value)
        return value

    match = _DIE_PATTERN.search(filename) or _DIE_PATTERN.search(path.name)
    if match:
        die, col, row = _die_fields(match)
        tags.update(die=die, die_col=col, die_row=row)
    else:
        tags.update(die=None, die_col=None, die_row=None)

    for field, regex in (
        ("X_filename", r"_X(-?\d+(?:\.\d+)?)"),
        ("Y_filename", r"_Y(-?\d+(?:\.\d+)?)"),
        ("Rz_filename", r"_Rz(-?\d+(?:\.\d+)?)"),
        ("L_tag", r"_L(\d+)(?:_|\.)"),
        ("D_tag", r"_D(\d+)(?:_|\.)"),
        ("S_tag", r"_S(\d+)(?:_|\.)"),
    ):
        found = re.search(regex, filename, flags=re.I)
        tags[field] = found.group(1) if found else None

    embedded_hex = re.search(r"_([0-9a-fA-F]{32})(?:\.[^.]+)?$", filename)
    azi = re.search(r"(?:^|_)AZI(-?\d+(?:\.\d+)?)(?:_|\.|$)", filename, re.I)
    die_source = filename
    die_token = re.search(r"_Die\d+", filename, re.I)
    if die_token is None:
        die_source = path.name
        die_token = re.search(r"_Die\d+", path.name, re.I)
    merged_fields = {
        field: business_value(field)
        for field in (
            "wafer_id",
            "lot_id",
            "tool_sn",
            "pad_name",
            "die_seq",
            "field_x",
            "field_y",
            "timestamp_raw",
        )
    }
    if all(
        merged_fields[field] not in (None, "")
        for field in ("wafer_id", "lot_id", "tool_sn", "die_seq", "timestamp_raw")
    ):
        metadata_status = "ok"
    elif any(value not in (None, "") for value in merged_fields.values()):
        metadata_status = "partial"
    else:
        metadata_status = "unrecognized"
    external_fills_value = any(
        getattr(embedded, field) in (None, "")
        and value not in (None, "")
        for field, value in merged_fields.items()
    )
    source_path = path.resolve()
    source_stat = filesystem_path(source_path).stat()
    return {
        "wafer_id_filename": business_value("wafer_id"),
        "lot_id_filename": business_value("lot_id"),
        "tool_sn_filename": business_value("tool_sn"),
        "pad_name_filename": business_value("pad_name"),
        "field_x_filename": business_value("field_x"),
        "field_y_filename": business_value("field_y"),
        "filename_time": parse_value("time"),
        "metadata_parse_status": metadata_status,
        "metadata_source": (
            "embedded"
            if not external_fills_value
            else "mixed"
            if embedded.parse_status != "unrecognized"
            else "external"
        ),
        "source_file": path.name,
        "source_path": str(source_path),
        "source_size_bytes": source_stat.st_size,
        "source_mtime_ns": source_stat.st_mtime_ns,
        "embedded_filename": filename,
        "filename_prefix_before_die": die_source[:die_token.start()] if die_token else None,
        "filename_timestamp_raw": business_value("timestamp_raw") or None,
        "embedded_common_hex_id": embedded_hex.group(1) if embedded_hex else None,
        "azi_filename_deg": float(azi.group(1)) if azi else None,
        "version": version,
        "declared_channel_count": channel_total,
        "global_header_tag": global_tag,
        "parser_version": PARSER_VERSION,
        **tags,
    }


def create_channel(
    base: dict[str, Any],
    header: dict[str, Any],
    channel_id: int,
    spectrum_type: str,
    wavelength: np.ndarray,
    numeric: np.ndarray,
    **other: Any,
) -> ParsedChannel:
    validate_wavelength(wavelength, spectrum_type)
    finite_columns = (
        numeric[:, [0, *range(8, 24)]]
        if spectrum_type == "mueller"
        else numeric
    )
    if not np.isfinite(finite_columns).all():
        raise ValueError(f"Non-finite {spectrum_type} data at channel {channel_id}")
    metadata = {
        **base,
        **header,
        "channel_id": channel_id,
        "channel_count": base["declared_channel_count"],
        "spectrum_type": spectrum_type,
        "wavelength_points": len(wavelength),
        "wavelength_min_nm": float(wavelength[0]),
        "wavelength_max_nm": float(wavelength[-1]),
        "parse_status": "ok",
        "parse_error": "",
        **other,
    }
    return ParsedChannel(metadata, numeric, spectrum_type)


def parse_counted_channels(
    reader: SMEReader, base: dict[str, Any], *, expanded: bool,
) -> list[ParsedChannel]:
    """Read counted arrays by structure; head, mode and version are metadata."""
    output = []
    for channel_id in range(1, base["declared_channel_count"] + 1):
        header = read_channel_header(reader)
        zero = reader.f64_array("zero_channel")
        # These are fixed metadata words, not empty vectors. Some heads store
        # nonzero settings here; their interpretation is deliberately left raw.
        prefix_words = [reader.u32() for _ in range(5)] if expanded else []
        wavelength = reader.f64_array("wavelength")
        validate_wavelength(wavelength, "wavelength")
        count = len(wavelength)
        if count > MAX_SPECTRAL_POINTS:
            raise ValueError(f"Unreasonable wavelength count {count}")
        scalars = [reader.f64_array(name) for name in ("psi", "delta", "N", "C", "S")]
        matrix = reader.f64_array("mueller")
        reflectance = reader.f64_array("reflectance")
        for index in range(2):
            reader.f64_array(f"reserved_{index}", expected=0)
        auxiliary = reader.f64_array("aux_raw")
        footer = reader.take(40)
        for name, values in (("zero_channel", zero), ("aux_raw", auxiliary),
                             ("reflectance", reflectance), *zip(("psi", "delta", "N", "C", "S"), scalars)):
            if len(values) not in (0, count):
                raise ValueError(f"{name}: length {len(values)}, expected 0 or {count}")
            if not np.isfinite(values).all():
                raise ValueError(f"Non-finite {name} data at channel {channel_id}")
        if len(matrix) not in (0, 16 * count) or not np.isfinite(matrix).all():
            raise ValueError(f"Invalid Mueller array at channel {channel_id}")
        has_scalars = all(len(values) == count for values in scalars)
        has_matrix = bool(np.count_nonzero(matrix))
        if reflectance.size:
            if has_matrix or any(values.size for values in scalars):
                raise UnsupportedSME("Combined reflectance and ellipsometry layout not verified")
            spectrum_type = "reflectance"
            numeric = np.column_stack((wavelength, reflectance))
        elif has_matrix:
            spectrum_type = "mueller"
            numeric = np.full((count, 24), np.nan, dtype=np.float64)
            numeric[:, 0] = wavelength
            for column, values in enumerate((*scalars, zero, auxiliary), start=1):
                if values.size:
                    numeric[:, column] = values
            numeric[:, 8:] = matrix.reshape(count, 16)
        elif has_scalars:
            # An all-zero Mij block is a serialized placeholder, not measured
            # Mueller data. Preserve the actual Psi/Delta/N/C/S vectors.
            spectrum_type = "ellipsometry"
            numeric = np.column_stack((wavelength, *scalars, *([auxiliary] if auxiliary.size else [])))
        else:
            raise UnsupportedSME("No supported measured series in channel")
        output.append(create_channel(
            base, header, channel_id, spectrum_type, wavelength, numeric,
            serialized_layout="expanded" if expanded else "compact",
            series_prefix_words=str(prefix_words), auxiliary_units="unknown",
            mij_status="measured" if has_matrix else "all_zero_placeholder_not_measured" if matrix.size else "absent",
            footer_length=len(footer),
        ))
    if reader.pos != len(reader.data):
        raise ValueError(f"SME contains {len(reader.data) - reader.pos} unexpected bytes")
    return output


def parse_legacy_compressed(raw: bytes, path: Path) -> list[ParsedChannel]:
    """Read the verified fixed-capacity, little-endian legacy record."""
    expected_size, capacity = 418540, 1025
    decoder = zlib.decompressobj()
    try:
        data = decoder.decompress(raw, expected_size + 1)
    except zlib.error as error:
        raise ValueError("Invalid compressed SME data") from error
    if (len(data) != expected_size or not decoder.eof
            or decoder.unused_data or decoder.unconsumed_tail):
        raise UnsupportedSME("Unverified or truncated compressed SME layout")
    if struct.unpack_from("<I", data)[0] != 1:
        raise UnsupportedSME("Legacy multi-channel layout not verified")
    version = data[4:12].split(b"\0", 1)[0].decode("ascii")
    filename = data[210:338].split(b"\0", 1)[0].decode("utf-8")
    values = np.frombuffer(data, dtype="<f4", offset=340)
    wavelength_buffer = values[:capacity]
    count = int(np.count_nonzero(wavelength_buffer))
    if count == 0 or np.any(wavelength_buffer[:count] <= 0) or np.any(wavelength_buffer[count:]):
        raise ValueError("Legacy wavelength array has invalid padding or values")
    wavelength = wavelength_buffer[:count].astype(np.float64)
    matrix_buffer = values[2 * capacity:18 * capacity].reshape(capacity, 16)
    parameters = values[66 * capacity:71 * capacity].reshape(capacity, 5)
    if (np.any(matrix_buffer[count:]) or np.any(parameters[count:])
            or np.any(parameters[:, 2:])
            or np.any(values[18 * capacity:66 * capacity])
            or np.any(values[71 * capacity:98 * capacity])
            or np.any(values[99 * capacity:])):
        raise UnsupportedSME("Legacy reserved data differs from the verified layout")
    matrix = matrix_buffer[:count].astype(np.float64)
    if not np.allclose(matrix[:, 0], 1.0, rtol=0, atol=1e-6):
        raise ValueError("Legacy normalized Mueller M00 is invalid")
    numeric = np.full((count, 24), np.nan)
    numeric[:, 0] = wavelength
    numeric[:, 1:3] = parameters[:count, :2]
    numeric[:, 6] = values[capacity:capacity + count]
    numeric[:, 7] = values[98 * capacity:98 * capacity + count]
    numeric[:, 8:] = matrix
    if not np.isfinite(numeric[:, [0, 1, 2, 6, 7]]).all():
        raise ValueError("Non-finite legacy spectral data")
    aoi, angle_radians = struct.unpack_from("<dd", data, 12)
    header = {"instrument": "", "mode": "", "sample_id": "", "sample_type": 1,
              "angle_1_deg": aoi if math.isclose(math.radians(aoi), angle_radians, abs_tol=1e-5) else None,
              "angle_2_deg": None, "angle_3_deg": None, "coord_x": None, "coord_y": None}
    return [create_channel(
        base_metadata(path, version, filename, 1, None), header, 1, "mueller", wavelength, numeric,
        serialized_layout="legacy_fixed_float32", envelope="zlib", legacy_capacity=capacity,
        legacy_ncs_status="not_stored", auxiliary_units="unknown",
        legacy_unknown_angle_92=struct.unpack_from("<d", data, 92)[0],
    )]


def parse_one(path: Path) -> list[ParsedChannel]:
    with filesystem_path(path.resolve()).open("rb") as stream:
        prefix = stream.read(16)
        if prefix.startswith(b"%TSD-Header-###%"):
            raise EncryptedSME(
                "TSD encrypted file: export a decrypted SME copy from an authorized "
                "application/environment, then load that copy."
            )
        raw = prefix + stream.read()
    if (len(raw) >= 2 and raw[0] & 15 == 8 and (raw[0] * 256 + raw[1]) % 31 == 0):
        return parse_legacy_compressed(raw, path)
    if not raw.startswith(b"SE3"):
        raise UnsupportedSME("Missing SE3 envelope")
    try:
        payload = base64.b64decode(raw[3:].strip(), validate=True)
    except Exception as error:
        raise ValueError("Invalid SME Base64") from error
    reader = SMEReader(payload)
    version = reader.qstring()
    channel_count = reader.u32()
    if not 1 <= channel_count <= 128:
        raise UnsupportedSME(f"Invalid channel count {channel_count}")
    embedded_name = reader.qstring()
    start = reader.pos
    matches, errors = [], []
    # The optional global word and numeric layout are structural candidates.
    # Version/head spelling is preserved as metadata, not an allowlist.
    for shift in (0, 4):
        reader.pos = start
        try:
            global_tag = reader.u32() if shift else None
        except ValueError as error:
            errors.append(str(error))
            continue
        at = reader.pos
        common = base_metadata(path, version, embedded_name, channel_count, global_tag)
        for expanded in (False, True):
            reader.pos = at
            try:
                channels = parse_counted_channels(reader, common, expanded=expanded)
            except ValueError as error:
                errors.append(str(error))
                continue
            matches.append(channels)
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise UnsupportedSME("Ambiguous SME numeric layout; refusing to guess")
    raise UnsupportedSME(f"No validated SME numeric layout matches (version {version!r}): "
                         + "; ".join(errors[:4]))


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _die_number(value: Any) -> int | None:
    number = _number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


@dataclass(frozen=True, slots=True)
class SpectrumIdentity:
    wafer: str
    lot: str
    pad: str
    die_seq: int | None
    timestamp: str
    tool_sn: str = ""
    field_x: int | None = None
    field_y: int | None = None
    parse_status: str = "ok"

    @property
    def display_name(self) -> str:
        return f"Die {self.die_seq}" if self.die_seq is not None else "Die ?"


def spectrum_identity(metadata: dict[str, Any]) -> SpectrumIdentity:
    """Use embedded-name business fields and fall back only for missing values."""
    instrument = str(metadata.get("instrument") or "")
    source_file = str(metadata.get("source_file") or "")
    if instrument == "BBSE" or source_file.casefold() == "test_sme.sme":
        return SpectrumIdentity(
            wafer="Simulation",
            lot="Unknown lot",
            pad="test_sme",
            die_seq=None,
            timestamp="",
            tool_sn="",
            parse_status="simulation",
        )

    parsed = parse_spectrum_filename(
        str(metadata.get("embedded_filename") or "")
        or str(metadata.get("filename_prefix_before_die") or "")
        or source_file
    )
    wafer = str(metadata.get("wafer_id_filename") or parsed.wafer_id or "").strip()
    lot = str(metadata.get("lot_id_filename") or parsed.lot_id or "").strip()
    tool_sn = str(metadata.get("tool_sn_filename") or parsed.tool_sn or "").strip()
    pad = str(metadata.get("pad_name_filename") or parsed.pad_name or "").strip()
    die_seq = _die_number(metadata.get("die"))
    if die_seq is None:
        die_seq = parsed.die_seq
    timestamp = _display_timestamp(metadata.get("filename_timestamp_raw"))
    if not timestamp:
        timestamp = parsed.time
    status = str(metadata.get("metadata_parse_status") or "").strip()
    if not status:
        status = "ok" if wafer and lot and tool_sn and die_seq is not None else "partial"
    return SpectrumIdentity(
        wafer=wafer,
        lot=lot,
        pad=pad,
        die_seq=die_seq,
        timestamp=timestamp,
        tool_sn=tool_sn,
        field_x=_die_number(metadata.get("field_x_filename"))
        if metadata.get("field_x_filename") is not None
        else parsed.field_x,
        field_y=_die_number(metadata.get("field_y_filename"))
        if metadata.get("field_y_filename") is not None
        else parsed.field_y,
        parse_status=status,
    )


def spectrum_coordinates(metadata: dict[str, Any]) -> tuple[float | None, float | None, str]:
    """Prefer header coordinates, but reject an all-zero placeholder when a
    concrete filename coordinate exists (the supplied DTS file has this case).
    """
    header_x, header_y = _number(metadata.get("coord_x")), _number(metadata.get("coord_y"))
    file_x, file_y = _number(metadata.get("X_filename")), _number(metadata.get("Y_filename"))
    if (
        header_x is not None
        and header_y is not None
        and not (header_x == 0 and header_y == 0 and (file_x or file_y))
    ):
        return header_x, header_y, "header"
    if file_x is not None and file_y is not None:
        return file_x, file_y, "filename"
    return None, None, "missing"


def natural_key(value: Any) -> tuple:
    text = str(value or "").casefold()
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part)
        for part in re.split(r"(\d+)", text)
        if part
    )


@dataclass(frozen=True, slots=True)
class ChannelKey:
    instrument: str
    channel_id: int
    aoi_deg: float | None
    azi_deg: float | None
    spectrum_type: str

    @property
    def sort_key(self) -> tuple:
        return (
            natural_key(self.instrument),
            self.channel_id,
            -math.inf if self.aoi_deg is None else self.aoi_deg,
            -math.inf if self.azi_deg is None else self.azi_deg,
            self.spectrum_type,
        )

    @property
    def legend_label(self) -> str:
        aoi = "?" if self.aoi_deg is None else f"{self.aoi_deg:.0f}°"
        azi = "?" if self.azi_deg is None else f"{self.azi_deg:.0f}°"
        return f"{self.instrument} · CH{self.channel_id} · AOI {aoi} · AZI {azi}"


@dataclass(frozen=True, slots=True)
class SpectrumChannel:
    metadata: dict[str, Any]
    wavelength: np.ndarray
    numeric: np.ndarray
    spectrum_type: str

    @property
    def channel_id(self) -> int:
        return int(self.metadata["channel_id"])

    @property
    def instrument(self) -> str:
        return str(self.metadata.get("instrument") or "Unknown instrument")

    @property
    def key(self) -> ChannelKey:
        return ChannelKey(
            instrument=self.instrument,
            channel_id=self.channel_id,
            aoi_deg=_number(self.metadata.get("angle_1_deg")),
            azi_deg=_number(self.metadata.get("angle_3_deg")),
            spectrum_type=self.spectrum_type,
        )

    def series(self, metric: str) -> np.ndarray | None:
        if metric in M_COL_INDEX:
            if self.spectrum_type != "mueller":
                return None
            index = M_COL_INDEX[metric]
        else:
            if metric in {"N", "C", "S"}:
                if self.spectrum_type not in {"mueller", "ellipsometry"}:
                    return None
                index = {"N": 3, "C": 4, "S": 5}[metric]
            elif metric in {"psi", "delta"}:
                if self.spectrum_type not in {"mueller", "ellipsometry"}:
                    return None
                index = 1 if metric == "psi" else 2
            elif metric == "reflectance":
                if self.spectrum_type != "reflectance":
                    return None
                index = 1
            elif metric == "aux":
                if self.spectrum_type == "reflectance":
                    return None
                index = 6 if self.spectrum_type == "ellipsometry" else 7
            else:
                index = None
        if index is None or index >= self.numeric.shape[1]:
            return None
        values = self.numeric[:, index]
        return values if np.isfinite(values).any() else None


@dataclass(frozen=True, slots=True)
class SpectrumFile:
    path: Path
    key: str
    size_bytes: int
    mtime_ns: int
    identity: SpectrumIdentity
    embedded_filename: str
    channels: tuple[SpectrumChannel, ...]
    x_mm: float | None
    y_mm: float | None
    coordinate_source: str

    @property
    def sort_key(self) -> tuple:
        return (
            natural_key(self.identity.wafer),
            natural_key(self.identity.lot),
            natural_key(self.identity.pad),
            math.inf if self.identity.die_seq is None else self.identity.die_seq,
            natural_key(self.identity.timestamp),
            os.path.normcase(str(self.path)),
        )

    @property
    def is_simulation(self) -> bool:
        return self.identity.wafer == "Simulation"

    @property
    def has_map_point(self) -> bool:
        return not self.is_simulation and self.x_mm is not None and self.y_mm is not None

    @property
    def channel_keys(self) -> tuple[ChannelKey, ...]:
        return tuple(sorted({channel.key for channel in self.channels}, key=lambda key: key.sort_key))


def file_metadata_dataframe(spectra) -> Any:
    """One participation row per SME, including files with multiple channels."""
    import pandas as pd
    return pd.DataFrame.from_records([
        {"Cur SME File Path": str(s.path), "Wafer ID": s.identity.wafer,
         "Lot ID": s.identity.lot, "PAD Name": s.identity.pad,
         "Die Seq": s.identity.die_seq, "SME Name": s.path.name,
         "Tool SN": s.identity.tool_sn, "FIELD X": s.identity.field_x,
         "FIELD Y": s.identity.field_y, "Time": s.identity.timestamp,
         "Folder": str(s.path.parent), "Instrument": ", ".join(dict.fromkeys(c.instrument for c in s.channels)),
         "Channel Count": len(s.channels)} for s in spectra], columns=[
             "Cur SME File Path", "Wafer ID", "Lot ID", "PAD Name", "Die Seq", "SME Name",
             "Tool SN", "FIELD X", "FIELD Y", "Time", "Folder", "Instrument", "Channel Count"])


def metadata_dataframe(spectra) -> Any:
    """Return one Excel-friendly metadata row for every parsed channel."""
    import pandas as pd

    records = []
    for spectrum in spectra:
        identity = spectrum.identity
        for channel in spectrum.channels:
            metadata = channel.metadata
            records.append({
                "Wafer ID": identity.wafer,
                "SME Name": spectrum.path.name,
                "Lot ID": identity.lot,
                "Tool SN": identity.tool_sn,
                "PAD Name": identity.pad,
                "Die Seq": identity.die_seq,
                "FIELD X": identity.field_x,
                "FIELD Y": identity.field_y,
                "Time": identity.timestamp,
                "Folder": str(spectrum.path.parent),
                "Instrument": channel.instrument,
                "Mode": metadata.get("mode"),
                "Version": metadata.get("version"),
                "Sample ID": metadata.get("sample_id"),
                "Channel Count": metadata.get("channel_count"),
                "Channel ID": metadata.get("channel_id"),
                "Metadata Parse Status": identity.parse_status,
                "Spectrum Parse Status": metadata.get("parse_status"),
                "Parse Error": metadata.get("parse_error"),
            })
    return pd.DataFrame.from_records(records, columns=METADATA_COLUMNS)


def write_metadata_csv(frame, path: Path) -> Path:
    """Write channel metadata exactly once per row for Excel-compatible import."""
    target = Path(path)
    frame.to_csv(target, index=False, encoding="utf-8-sig")
    return target


def parse_sme_file(path: Path) -> SpectrumFile:
    path = Path(path)
    parsed = parse_one(path)
    if not parsed:
        raise UnsupportedSME("SME contains no readable channels")
    metadata = parsed[0].metadata
    identity = spectrum_identity(metadata)
    channels = tuple(
        SpectrumChannel(
            metadata=dict(channel.metadata),
            wavelength=channel.numeric[:, 0].copy(),
            numeric=channel.numeric,
            spectrum_type=channel.spectrum_type,
        )
        for channel in parsed
    )
    x_mm, y_mm, source = spectrum_coordinates(metadata)
    source_path = Path(metadata["source_path"])
    return SpectrumFile(
        path=source_path,
        key=os.path.normcase(str(source_path)),
        size_bytes=metadata["source_size_bytes"],
        mtime_ns=metadata["source_mtime_ns"],
        identity=identity,
        embedded_filename=str(metadata.get("embedded_filename") or path.name),
        channels=channels,
        x_mm=x_mm,
        y_mm=y_mm,
        coordinate_source=source,
    )


@dataclass(frozen=True, slots=True)
class LoadIssue:
    path: Path
    status: str
    message: str


@dataclass(frozen=True, slots=True)
class LoadResult:
    spectra: tuple[SpectrumFile, ...]
    issues: tuple[LoadIssue, ...]
    cancelled: bool = False


def scan_sme_files(
    folder: Path,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> list[Path]:
    folder = Path(folder)
    io_folder = filesystem_path(folder.resolve())
    if not io_folder.is_dir():
        raise ValueError("Spectrum folder does not exist")
    paths: list[Path] = []
    errors: list[OSError] = []
    for root, _directories, filenames in os.walk(io_folder, onerror=errors.append):
        if cancelled and cancelled():
            break
        for filename in filenames:
            path = folder / Path(root).relative_to(io_folder) / filename
            if path.suffix.casefold() == ".sme":
                paths.append(path)
    if errors and not paths:
        raise errors[0]
    return sorted(paths, key=lambda path: tuple(natural_key(part) for part in path.parts))


def load_folder(
    folder: Path,
    *,
    progress: Callable[[int, int, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> LoadResult:
    if progress:
        progress(0, 0, "Scanning spectrum folders…")
    paths = scan_sme_files(folder, cancelled=cancelled)
    spectra: list[SpectrumFile] = []
    issues: list[LoadIssue] = []
    total = len(paths)
    if cancelled and cancelled():
        return LoadResult((), (), True)
    if progress:
        progress(0, total, "Scanning spectrum folders…")
    for index, path in enumerate(paths, 1):
        if cancelled and cancelled():
            return LoadResult(tuple(spectra), tuple(issues), True)
        try:
            spectra.append(parse_sme_file(path))
        except Exception as error:
            status = ("encrypted" if isinstance(error, EncryptedSME)
                      else "unsupported" if isinstance(error, UnsupportedSME) else "error")
            issues.append(LoadIssue(path, status, str(error)))
        if progress:
            progress(index, total, path.name)
    return LoadResult(tuple(spectra), tuple(issues), bool(cancelled and cancelled()))


@dataclass(frozen=True, slots=True)
class MergeReport:
    added: int
    replaced: int
    skipped: int
    issues: int


class SpectrumCatalog:
    """One merged spectrum collection with stable path identity."""

    def __init__(self):
        self._files: dict[str, SpectrumFile] = {}
        self._ordered: tuple[SpectrumFile, ...] | None = None
        self.issues: list[LoadIssue] = []

    def replace(self, result: LoadResult) -> None:
        self._files = {spectrum.key: spectrum for spectrum in result.spectra}
        self._ordered = None
        self.issues = list(result.issues)

    def merge(self, result: LoadResult) -> MergeReport:
        added = replaced = skipped = 0
        for spectrum in result.spectra:
            current = self._files.get(spectrum.key)
            if current is None:
                self._files[spectrum.key] = spectrum
                added += 1
            elif (
                current.size_bytes == spectrum.size_bytes
                and current.mtime_ns == spectrum.mtime_ns
            ):
                skipped += 1
            else:
                self._files[spectrum.key] = spectrum
                replaced += 1
        self.issues = list(dict.fromkeys((*self.issues, *result.issues)))
        if added or replaced:
            self._ordered = None
        return MergeReport(added, replaced, skipped, len(result.issues))

    def remove(self, keys: Iterable[str]) -> int:
        removed = 0
        for key in set(keys):
            if self._files.pop(key, None) is not None:
                removed += 1
        if removed:
            self._ordered = None
        return removed

    @property
    def spectra(self) -> tuple[SpectrumFile, ...]:
        if self._ordered is None:
            self._ordered = tuple(
                sorted(self._files.values(), key=lambda spectrum: spectrum.sort_key)
            )
        return self._ordered

    def grouped(self, group_by: str = "wafer") -> dict:
        if group_by not in SPECTRUM_GROUP_FIELDS:
            raise ValueError(f"Unknown spectrum grouping: {group_by}")
        fields = SPECTRUM_GROUP_FIELDS[group_by]

        def values(spectrum):
            identity = spectrum.identity
            return tuple(identity.die_seq if field == "die" else getattr(identity, field)
                         for field in fields)

        groups = {}
        # The catalog already orders spectra by complete source identity/Die/time.
        # Sort the much smaller branch keys, retaining that order within leaves.
        for spectrum in self.spectra:
            path = values(spectrum)
            branch = groups
            for value in path[:-1]:
                branch = branch.setdefault(value, {})
            branch.setdefault(path[-1], []).append(spectrum)
        def order(branch, depth):
            return {key: order(branch[key], depth + 1) if depth < len(fields) - 1 else branch[key]
                    for key in sorted(branch, key=lambda value: (value is None, natural_key(value)))}
        return order(groups, 0)

    @property
    def channel_count(self) -> int:
        channels = set()
        for spectrum in self._files.values():
            for channel in spectrum.channels:
                key = channel.key
                if key.aoi_deg is not None and key.azi_deg is not None:
                    channels.add((key.instrument, "angles", key.aoi_deg, key.azi_deg))
                else:
                    channels.add((key.instrument, "channel", key.channel_id))
        return len(channels)

    def metadata_dataframe(self):
        return metadata_dataframe(self.spectra)

