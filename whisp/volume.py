"""System-volume control via the Windows Core Audio API.

winmm's waveOutSetVolume only drives the legacy WAVE_MAPPER device, which
on modern Windows is often NOT the endpoint the user actually hears — the
call can return success while the audible volume never changes. The Core
Audio COM interface IAudioEndpointVolume is the same control the Windows
volume flyout uses, reached here through pure ctypes (no extra
dependencies). The setter raises on any failure so callers never announce
a change that did not happen.
"""
import ctypes
from ctypes import (
    POINTER, Structure, WINFUNCTYPE, byref, c_float, c_long, c_ubyte,
    c_ulong, c_ushort, c_void_p, cast, windll,
)

CLSCTX_ALL = 0x17
ERender, EConsole = 0, 0
HRESULT = c_long


class _GUID(Structure):
    _fields_ = [("Data1", c_ulong), ("Data2", c_ushort), ("Data3", c_ushort),
                ("Data4", c_ubyte * 8)]


def _guid(d1, d2, d3, d4):
    return _GUID(d1, d2, d3, (c_ubyte * 8)(*d4))


CLSID_MMDEVICE_ENUMERATOR = _guid(
    0xBCDE0395, 0xE52F, 0x467C, (0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69,
                                0x2E))
IID_DEVICE_ENUMERATOR = _guid(
    0xA95664D2, 0x9614, 0x4F35, (0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17,
                                0xE6))
IID_AUDIO_ENDPOINT_VOLUME = _guid(
    0x5CDF2C82, 0x841E, 0x4546, (0x97, 0x22, 0x0C, 0xF7, 0x40, 0x78, 0x22,
                                0x9A))


def _vtbl(obj):
    """The vtable (array of function pointers) of a COM interface."""
    return cast(obj, POINTER(POINTER(c_void_p))).contents


def _vmethod(obj, index, restype, *argtypes):
    """Return a bound callable for vtable slot `index` of the interface."""
    func = cast(_vtbl(obj)[index],
                WINFUNCTYPE(restype, c_void_p, *argtypes))
    return func


def _endpoint_volume():
    """Open IAudioEndpointVolume for the default render (speakers)
    endpoint, or return None if any COM step fails."""
    try:
        ole32 = windll.ole32
        ole32.CoInitialize(None)  # safe to call repeatedly; never uninit
        ole32.CoCreateInstance.argtypes = [
            POINTER(_GUID), c_void_p, c_ulong, POINTER(_GUID),
            POINTER(c_void_p)]
        ole32.CoCreateInstance.restype = HRESULT
        p_enum = c_void_p()
        hr = ole32.CoCreateInstance(
            byref(CLSID_MMDEVICE_ENUMERATOR), None, CLSCTX_ALL,
            byref(IID_DEVICE_ENUMERATOR), byref(p_enum))
        if hr < 0 or not p_enum:
            return None
        p_device = c_void_p()
        get_default = _vmethod(p_enum, 4, HRESULT, ctypes.c_int,
                               ctypes.c_int, POINTER(c_void_p))
        if get_default(p_enum, ERender, EConsole, byref(p_device)) < 0 \
                or not p_device:
            return None
        p_volume = c_void_p()
        activate = _vmethod(p_device, 3, HRESULT, POINTER(_GUID), c_ulong,
                            c_void_p, POINTER(c_void_p))
        if activate(p_device, byref(IID_AUDIO_ENDPOINT_VOLUME), CLSCTX_ALL,
                    None, byref(p_volume)) < 0 or not p_volume:
            return None
        return p_volume
    except Exception:
        return None


def current_volume():
    """Return the current system volume (0-100) of the default audio
    endpoint, or None when it cannot be read."""
    p_volume = _endpoint_volume()
    if p_volume is None:
        return None
    try:
        level = c_float()
        get_scalar = _vmethod(p_volume, 9, HRESULT, POINTER(c_float))
        if get_scalar(p_volume, byref(level)) < 0:
            return None
        return int(round(max(0.0, min(1.0, level.value)) * 100))
    except Exception:
        return None


def set_volume_level(level):
    """Set the system volume to `level` percent (0-100) on the default
    audio endpoint. Raises OSError when the endpoint cannot be reached or
    rejects the change."""
    p_volume = _endpoint_volume()
    if p_volume is None:
        raise OSError("no audio endpoint available")
    lvl = max(0.0, min(1.0, int(level) / 100.0))
    try:
        set_scalar = _vmethod(p_volume, 7, HRESULT, c_float, c_void_p)
        hr = set_scalar(p_volume, lvl, None)
        if hr < 0:
            raise OSError(f"SetMasterVolumeLevelScalar failed "
                          f"(HRESULT {hr:#x})")
    except Exception as e:
        if isinstance(e, OSError):
            raise
        raise OSError(f"could not set volume: {e}") from e
