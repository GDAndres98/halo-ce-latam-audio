"""Read the leading frame flags of CELT 0.11.0 packets (diagnostics only; pure Python).

A minimal port of the CELT 0.11.0 range decoder (libcelt/entdec.c) and of the first symbols that
celt_decode_with_ec() reads from every packet (libcelt/celt.c), in order:

    silence      ec_dec_bit_logp(15)                    only if ec_tell() == 1
    post-filter  ec_dec_bit_logp(1)                     if start == 0 and tell + 16 <= total bits
                 then octave = ec_dec_uint(6), period = (16 << octave) + ec_dec_bits(4 + octave) - 1,
                 gain = ec_dec_bits(3), tapset = ec_dec_icdf([2, 1, 0], 2) if tell + 2 <= total
                 (a decoder built without ENABLE_POSTFILTER returns CELT_CORRUPTED_DATA here)
    transient    ec_dec_bit_logp(3)                     if LM > 0 and tell + 3 <= total bits
    intra energy ec_dec_bit_logp(3)                     if tell + 3 <= total bits

For MCC's custom mode (44,100 Hz, 512-sample frames) LM = 2. Nothing else of the packet is decoded.
"""

EC_SYM_BITS = 8
EC_CODE_BITS = 32
EC_SYM_MAX = (1 << EC_SYM_BITS) - 1
EC_CODE_TOP = 1 << (EC_CODE_BITS - 1)
EC_CODE_BOT = EC_CODE_TOP >> EC_SYM_BITS
EC_CODE_EXTRA = (EC_CODE_BITS - 2) % EC_SYM_BITS + 1
EC_WINDOW_SIZE = 32
EC_UINT_BITS = 8
TAPSET_ICDF = (2, 1, 0)


def _ilog(v):
    return v.bit_length()


class RangeDecoder:
    def __init__(self, buf):
        self.buf, self.storage = bytes(buf), len(buf)
        self.offs = self.end_offs = self.end_window = self.nend_bits = 0
        self.nbits_total = EC_CODE_BITS + 1 - ((EC_CODE_BITS - EC_CODE_EXTRA) // EC_SYM_BITS) * EC_SYM_BITS
        self.rng = 1 << EC_CODE_EXTRA
        self.rem = self._read_byte()
        self.val = self.rng - 1 - (self.rem >> (EC_SYM_BITS - EC_CODE_EXTRA))
        self._normalize()

    def _read_byte(self):
        if self.offs < self.storage:
            b = self.buf[self.offs]
            self.offs += 1
            return b
        return 0

    def _read_byte_from_end(self):
        if self.end_offs < self.storage:
            self.end_offs += 1
            return self.buf[self.storage - self.end_offs]
        return 0

    def _normalize(self):
        while self.rng <= EC_CODE_BOT:
            self.nbits_total += EC_SYM_BITS
            self.rng = (self.rng << EC_SYM_BITS) & 0xFFFFFFFF
            sym = self.rem
            self.rem = self._read_byte()
            sym = ((sym << EC_SYM_BITS) | self.rem) >> (EC_SYM_BITS - EC_CODE_EXTRA)
            self.val = ((self.val << EC_SYM_BITS) + (EC_SYM_MAX & ~sym)) & (EC_CODE_TOP - 1)

    def tell(self):
        return self.nbits_total - _ilog(self.rng)

    def bit_logp(self, logp):
        r, d = self.rng, self.val
        s = r >> logp
        ret = d < s
        if not ret:
            self.val = d - s
        self.rng = s if ret else r - s
        self._normalize()
        return int(ret)

    def _decode(self, ft):
        self.ext = self.rng // ft
        s = self.val // self.ext
        return ft - min(s + 1, ft)

    def _update(self, fl, fh, ft):
        s = self.ext * (ft - fh)
        self.val -= s
        self.rng = self.ext * (fh - fl) if fl > 0 else self.rng - s
        self._normalize()

    def uint(self, ft):
        ft -= 1
        ftb = _ilog(ft)
        if ftb > EC_UINT_BITS:
            ftb -= EC_UINT_BITS
            ft1 = (ft >> ftb) + 1
            s = self._decode(ft1)
            self._update(s, s + 1, ft1)
            return (s << ftb) | self.bits(ftb)
        ft += 1
        s = self._decode(ft)
        self._update(s, s + 1, ft)
        return s

    def bits(self, n):
        window, available = self.end_window, self.nend_bits
        if available < n:
            while True:
                window |= self._read_byte_from_end() << available
                available += EC_SYM_BITS
                if available > EC_WINDOW_SIZE - EC_SYM_BITS:
                    break
        ret = window & ((1 << n) - 1)
        self.end_window, self.nend_bits = window >> n, available - n
        self.nbits_total += n
        return ret

    def icdf(self, icdf, ftb):
        s, d = self.rng, self.val
        r = s >> ftb
        ret = -1
        while True:
            t = s
            ret += 1
            s = r * icdf[ret]
            if d >= s:
                break
        self.val = d - s
        self.rng = t - s
        self._normalize()
        return ret


def frame_flags(packet, lm=2, start=0):
    """Leading flags of one CELT 0.11 packet: silence, post-filter (+ params), transient, intra."""
    dec = RangeDecoder(packet)
    total = len(packet) * 8
    out = {"silence": 0, "postfilter": 0, "pf_period": None, "pf_gain_q": None, "pf_tapset": None,
           "transient": 0, "intra": 0}
    tell = dec.tell()
    if tell == 1:
        out["silence"] = dec.bit_logp(15)
    if out["silence"]:
        return out
    if start == 0 and tell + 16 <= total:
        if dec.bit_logp(1):
            out["postfilter"] = 1
            octave = dec.uint(6)
            out["pf_period"] = (16 << octave) + dec.bits(4 + octave) - 1
            out["pf_gain_q"] = dec.bits(3)
            if dec.tell() + 2 <= total:
                out["pf_tapset"] = dec.icdf(TAPSET_ICDF, 2)
        tell = dec.tell()
    if lm > 0 and tell + 3 <= total:
        out["transient"] = dec.bit_logp(3)
        tell = dec.tell()
    if tell + 3 <= total:
        out["intra"] = dec.bit_logp(3)
    return out
