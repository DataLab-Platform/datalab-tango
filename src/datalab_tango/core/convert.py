"""Conversion of received values to signals and images.

Each object holds a copy of the value, calibrated as described by the profile,
and records its origin in the ``experimental_source`` metadata entry (device,
attribute, device and reception times, quality, profile).
"""

from __future__ import annotations

import datetime

import numpy as np
from sigima.io.common.converters import convert_array_to_valid_dtype
from sigima.objects import (
    ImageObj,
    SignalObj,
    create_image,
    create_signal,
    make_experimental_source,
    set_experimental_source,
)

from .profile import AttributeKind, AttributeProfile, DeviceProfile
from .reception import Reading

__all__ = ["reading_to_object"]


def _iso(timestamp: float) -> str:
    """Return a time stamp (s since the epoch) as an ISO 8601 UTC string."""
    return datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).isoformat()


def reading_to_object(
    reading: Reading, profile: DeviceProfile, attribute: AttributeProfile, title: str
) -> SignalObj | ImageObj:
    """Return the signal or image holding a received value.

    Raises:
        ValueError: if the value does not have the dimensions of its kind
    """
    value = np.asarray(reading.value)
    conversions: list[str] = []
    label = attribute.label or attribute.name
    if attribute.kind is AttributeKind.SIGNAL:
        if value.ndim != 1:
            raise ValueError(
                f"'{attribute.name}' is a {value.ndim}D value, not a spectrum"
            )
        x = attribute.x.origin + attribute.x.step * np.arange(value.size)
        y = value if np.iscomplexobj(value) else value.astype(float)
        if y.dtype != value.dtype:
            conversions.append(f"{value.dtype} -> {y.dtype}")
        obj = create_signal(
            title,
            x,
            y,
            units=(attribute.x.unit, attribute.unit),
            labels=(attribute.x.label, label),
        )
    else:
        if value.ndim != 2:
            raise ValueError(
                f"'{attribute.name}' is a {value.ndim}D value, not an image"
            )
        data = convert_array_to_valid_dtype(value, ImageObj.VALID_DTYPES)
        if data.dtype != value.dtype:
            conversions.append(f"{value.dtype} -> {data.dtype}")
        obj = create_image(title, np.array(data, copy=True))
        obj.set_uniform_coords(
            attribute.x.step, attribute.y.step, attribute.x.origin, attribute.y.origin
        )
        obj.xunit, obj.yunit, obj.zunit = (
            attribute.x.unit,
            attribute.y.unit,
            attribute.unit,
        )
        obj.xlabel, obj.ylabel, obj.zlabel = attribute.x.label, attribute.y.label, label
    timestamps = {"reception": _iso(reading.reception_time)}
    if reading.source_time is not None:
        timestamps["source"] = _iso(reading.source_time)
    source = make_experimental_source(
        "tango",
        profile.device,
        entry=attribute.name,
        timestamps=timestamps,
        conversions=conversions or None,
        details={
            "profile": profile.name,
            "quality": reading.quality,
            "reading": reading.number,
        },
    )
    set_experimental_source(obj, source)
    return obj
