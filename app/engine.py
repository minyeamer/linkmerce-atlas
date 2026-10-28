"""Wirelog 공개 C API를 사용하는 도달 관계 계산기."""
import ctypes as C
import ctypes.util
import os
from pathlib import Path


class Wirelog:
    def __init__(self, edges: set[tuple[int, int]]):
        library = os.getenv("WIRELOG_LIBRARY") or ctypes.util.find_library("wirelog")
        if not library:
            raise RuntimeError("Wirelog library not found; run with Docker")
        self.lib = C.CDLL(library)
        self.session = C.c_void_p()
        self.lib.wirelog_easy_open.argtypes = [C.c_char_p, C.POINTER(C.c_void_p)]
        self.lib.wirelog_easy_open.restype = C.c_int
        self.lib.wirelog_easy_close.argtypes = [C.c_void_p]
        for name in ("wirelog_easy_insert", "wirelog_easy_remove"):
            method = getattr(self.lib, name)
            method.argtypes = [C.c_void_p, C.c_char_p, C.POINTER(C.c_int64), C.c_uint32]
            method.restype = C.c_int
        self.lib.wirelog_easy_step.argtypes = [C.c_void_p]
        self.lib.wirelog_easy_step.restype = C.c_int
        self.callback_type = C.CFUNCTYPE(None, C.c_char_p, C.POINTER(C.c_int64), C.c_uint32, C.c_int32, C.c_void_p)
        self.lib.wirelog_easy_set_delta_cb.argtypes = [C.c_void_p, self.callback_type, C.c_void_p]
        self.lib.wirelog_easy_set_delta_cb.restype = C.c_int
        self.pairs: set[tuple[int, int]] = set()
        self.callback = self.callback_type(self._delta)
        rules = Path(__file__).parents[1] / "ontology/linkmerce.dl"
        self._check(self.lib.wirelog_easy_open(rules.read_bytes(), C.byref(self.session)))
        try:
            self._check(self.lib.wirelog_easy_set_delta_cb(self.session, self.callback, None))
            for source, target in sorted(edges):
                self._check(self.lib.wirelog_easy_insert(self.session, b"dependency", (C.c_int64 * 2)(source, target), 2))
            self._check(self.lib.wirelog_easy_step(self.session))
        finally:
            self.lib.wirelog_easy_close(self.session)
            self.session = C.c_void_p()

    def _delta(self, relation, row, ncols, diff, context):
        if relation == b"reaches" and ncols == 2:
            pair = (int(row[0]), int(row[1]))
            if diff > 0:
                self.pairs.add(pair)
            elif diff < 0:
                self.pairs.discard(pair)

    @staticmethod
    def _check(code):
        if code:
            raise RuntimeError(f"Wirelog evaluation failed: {code}")
