"""Windows Explorer's native Open dialog configured for multiple folders."""
import ctypes
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID


CLSID_FILE_OPEN_DIALOG = "DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7"
IID_FILE_OPEN_DIALOG = "D57C7288-D4AD-4768-BE02-9D969532D960"
IID_SHELL_ITEM = "43826D1E-E718-42EE-BC55-A1E261C37BFE"
FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_ALLOWMULTISELECT = 0x200
SIGDN_FILESYSPATH = 0x80058000
CANCELLED = ctypes.c_int32(0x800704C7).value


def _guid(value):
    return (ctypes.c_ubyte * 16).from_buffer_copy(UUID(value).bytes_le)


def _method(instance, slot, returns, *argtypes):
    vtable = ctypes.cast(instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(returns, ctypes.c_void_p, *argtypes)(vtable[slot])


def _check(result):
    if result < 0:
        raise ctypes.WinError(result)


def _invoke(instance, slot, argtypes, *args):
    _check(_method(instance, slot, ctypes.c_long, *argtypes)(instance, *args))


@contextmanager
def _owned_interface():
    instance = ctypes.c_void_p()
    try:
        yield instance
    finally:
        if instance.value is not None:
            _method(instance, 2, ctypes.c_ulong)(instance)  # IUnknown::Release


def _show(dialog, owner):
    return _method(dialog, 3, ctypes.c_long, ctypes.c_void_p)(dialog, owner)  # IModalWindow::Show


def choose_windows_folders(owner, title, directory=None):
    """Return selected filesystem paths. A cancelled dialog returns an empty tuple."""
    pointer = ctypes.c_void_p
    out_pointer = ctypes.POINTER(pointer)
    uint = ctypes.c_uint32
    ole = ctypes.WinDLL("ole32")
    shell = ctypes.WinDLL("shell32")
    initialize = ole.CoInitializeEx
    initialize.argtypes = [pointer, uint]
    initialize.restype = ctypes.c_long
    _check(initialize(None, 0x2 | 0x4))  # STA with OLE 1.0 DDE disabled
    try:
        create = ole.CoCreateInstance
        create.argtypes = [pointer, pointer, uint, pointer, out_pointer]
        create.restype = ctypes.c_long
        with _owned_interface() as dialog:
            _check(create(ctypes.byref(_guid(CLSID_FILE_OPEN_DIALOG)), None, 1,
                          ctypes.byref(_guid(IID_FILE_OPEN_DIALOG)), ctypes.byref(dialog)))
            flags = uint()
            _invoke(dialog, 10, (ctypes.POINTER(uint),), ctypes.byref(flags))  # GetOptions
            _invoke(dialog, 9, (uint,), flags.value | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM |
                    FOS_ALLOWMULTISELECT)  # SetOptions
            _invoke(dialog, 17, (ctypes.c_wchar_p,), title)  # SetTitle
            if directory:
                resolve = shell.SHCreateItemFromParsingName
                resolve.argtypes = [ctypes.c_wchar_p, pointer, pointer, out_pointer]
                resolve.restype = ctypes.c_long
                with _owned_interface() as folder:
                    if resolve(str(directory), None, ctypes.byref(_guid(IID_SHELL_ITEM)),
                               ctypes.byref(folder)) >= 0:
                        _invoke(dialog, 12, (pointer,), folder)  # SetFolder
            result = _show(dialog, owner)
            if result == CANCELLED:
                return ()
            _check(result)
            return _selected_paths(dialog, ole)
    finally:
        ole.CoUninitialize()


def _selected_paths(dialog, ole):
    pointer = ctypes.c_void_p
    out_pointer = ctypes.POINTER(pointer)
    uint = ctypes.c_uint32
    free = ole.CoTaskMemFree
    free.argtypes = [pointer]
    free.restype = None
    paths = []
    with _owned_interface() as items:
        _invoke(dialog, 27, (out_pointer,), ctypes.byref(items))  # IFileOpenDialog::GetResults
        count = uint()
        _invoke(items, 7, (ctypes.POINTER(uint),), ctypes.byref(count))  # IShellItemArray::GetCount
        for index in range(count.value):
            with _owned_interface() as item:
                _invoke(items, 8, (uint, out_pointer), index, ctypes.byref(item))  # GetItemAt
                buffer = pointer()
                _invoke(item, 5, (uint, out_pointer), SIGDN_FILESYSPATH, ctypes.byref(buffer))  # GetDisplayName
                try:
                    paths.append(Path(ctypes.wstring_at(buffer)))
                finally:
                    free(buffer)
    return tuple(paths)
