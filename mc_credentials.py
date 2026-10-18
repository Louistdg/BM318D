"""BM318d — coffre de clés.

Sous Windows : Windows Credential Manager (Advapi32), aucun repli en clair.
Hors Windows : le module s'importe et échoue proprement à l'usage
(« Coffre Windows indisponible »), pour que les connecteurs restent testables
sans stocker de secret.
"""
import ctypes
import sys
import uuid

WINDOWS = sys.platform == 'win32'
MESSAGE_HORS_WINDOWS = 'Coffre Windows indisponible (hors Windows)'


def target(connector_id):
    return 'BM318d/V2.2/connector/' + uuid.UUID(str(connector_id)).hex


if WINDOWS:
    from ctypes import wintypes as w

    class Credential(ctypes.Structure):
        _fields_ = [('Flags', w.DWORD), ('Type', w.DWORD), ('TargetName', w.LPWSTR),
                    ('Comment', w.LPWSTR), ('LastWritten', w.FILETIME),
                    ('CredentialBlobSize', w.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
                    ('Persist', w.DWORD), ('AttributeCount', w.DWORD), ('Attributes', ctypes.c_void_p),
                    ('TargetAlias', w.LPWSTR), ('UserName', w.LPWSTR)]

    def api():
        try:
            dll = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        except OSError:
            raise ValueError('Coffre Windows indisponible') from None
        dll.CredWriteW.argtypes = [ctypes.POINTER(Credential), w.DWORD]
        dll.CredWriteW.restype = w.BOOL
        dll.CredReadW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
        dll.CredReadW.restype = w.BOOL
        dll.CredDeleteW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD]
        dll.CredDeleteW.restype = w.BOOL
        dll.CredFree.argtypes = [ctypes.c_void_p]
        return dll
else:
    def api():
        raise ValueError(MESSAGE_HORS_WINDOWS)


def put(connector_id, secret):
    if not isinstance(secret, str) or not secret or len(secret.encode('utf-16-le')) > 2560:
        raise ValueError('Clé invalide ou trop longue')
    if not WINDOWS:
        raise ValueError(MESSAGE_HORS_WINDOWS)
    raw = secret.encode('utf-16-le')
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    cred = Credential(Type=1, TargetName=target(connector_id), CredentialBlobSize=len(raw),
                      CredentialBlob=blob, Persist=2, UserName='BM318d')
    if not api().CredWriteW(ctypes.byref(cred), 0):
        raise ValueError('Coffre Windows indisponible')


def get(connector_id):
    dll = api()
    pointer = ctypes.POINTER(Credential)()
    if not dll.CredReadW(target(connector_id), 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:
            return ''
        raise ValueError('Coffre Windows indisponible')
    try:
        return ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize).decode('utf-16-le')
    finally:
        dll.CredFree(pointer)


def delete(connector_id):
    dll = api()
    if not dll.CredDeleteW(target(connector_id), 1, 0) and ctypes.get_last_error() != 1168:
        raise ValueError('Coffre Windows indisponible')
