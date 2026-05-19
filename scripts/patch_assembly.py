import dnfile
import shutil
import struct
import sys

path = '/data/7dtd/server/7DaysToDieServer_Data/Managed/Assembly-CSharp.dll'
dn = dnfile.dnPE(path)

with open(path, 'rb') as f:
    data = bytearray(f.read())

def rva2off(rva):
    for s in dn.sections:
        va = s.VirtualAddress
        if va <= rva < va + s.SizeOfRawData:
            return rva - va + s.PointerToRawData
    return None

TARGETS = {
    # Only patch the two methods that crash in GameOptionsManager's static constructor.
    # Patching GUIWindowManager.Awake breaks its singleton init and causes
    # GameManager.Awake to NullRef at [0x00208], preventing server startup.
    'GameOptionsManager': ['ValidateFoV', 'ValidateFoV3P'],
}

typedefs = dn.net.mdtables.TypeDef.rows
methoddefs = dn.net.mdtables.MethodDef.rows
patched = []

for i, trow in enumerate(typedefs):
    tname = str(trow.TypeName)
    if tname not in TARGETS:
        continue

    method_refs = trow.MethodList
    target_methods = TARGETS[tname]
    print(f'Found type {tname}, methods: {len(method_refs)}')

    for mref in method_refs:
        try:
            mrow = mref.row
        except AttributeError:
            try:
                idx = mref.row_index - 1
                mrow = methoddefs[idx]
            except Exception as e:
                print(f'  Cannot access method row: {e}')
                continue

        mname = str(mrow.Name)
        if mname not in target_methods:
            continue

        rva = mrow.Rva
        if not isinstance(rva, int):
            rva = int(rva)
        if rva == 0:
            print(f'  SKIP {tname}.{mname}: abstract/extern')
            continue

        off = rva2off(rva)
        if off is None:
            print(f'  SKIP {tname}.{mname}: cannot map RVA')
            continue

        hdr = data[off]
        fmt = hdr & 0x3

        if fmt == 0x2:
            # Tiny: change header to 1-byte body, put ret
            old_size = (hdr >> 2) & 0x3F
            data[off] = 0x06       # tiny: 1 byte IL
            data[off + 1] = 0x2A  # ret
            print(f'  PATCH-TINY {tname}.{mname} @ {off:#x}: size {old_size}->1')
        elif fmt == 0x3:
            # Fat: convert to tiny by overwriting first 2 bytes.
            # The runtime loads method via RVA, not sequentially,
            # so orphaned bytes after off+1 are never read for this method.
            flags_word = struct.unpack_from('<H', data, off)[0]
            hdr_size = ((flags_word >> 12) & 0xF) * 4
            code_size = struct.unpack_from('<I', data, off + 4)[0]
            data[off] = 0x06       # tiny: 1 byte IL
            data[off + 1] = 0x2A  # ret
            print(f'  PATCH-FAT->TINY {tname}.{mname} @ {off:#x}: was {hdr_size}b hdr + {code_size}b code')
        else:
            print(f'  SKIP {tname}.{mname}: unknown format {hdr:#04x}')
            continue

        patched.append(f'{tname}.{mname}')

print(f'\nPatched {len(patched)}: {patched}')

if not patched:
    print('ERROR: No methods patched!')
    sys.exit(1)

bak = path + '.bak'
shutil.copy(path, bak)
print(f'Backup: {bak}')

with open(path, 'wb') as f:
    f.write(data)
print('Done.')
