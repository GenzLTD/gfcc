import os

def count_by_type(path):
    total = 0
    git_files = 0
    node_modules = 0
    venv_pycache = 0
    vendor_dist = 0
    other = 0
    for r, ds, fs in os.walk(path):
        for f in fs:
            total += 1
            fp = os.path.join(r, f).replace('\\', '/')
            if '/.git/' in fp or '.git/objects' in fp or '.git/refs' in fp:
                git_files += 1
            elif '/node_modules/' in fp:
                node_modules += 1
            elif '/.venv/' in fp or '/__pycache__/' in fp:
                venv_pycache += 1
            elif '/vendor/' in fp or '/dist/' in fp or '/build/' in fp or '/target/' in fp:
                vendor_dist += 1
            else:
                other += 1
    return total, git_files, node_modules, venv_pycache, vendor_dist, other

dirs = [
    ('surface-zervi/GitHub', 'D:/surface-zervi/GitHub'),
    ('Downloads', 'D:/Downloads'),
    ('DemoPPI', 'D:/DemoPPI'),
    ('MacSzjason72', 'D:/MacSzjason72'),
    ('zervi', 'D:/zervi'),
]

with open('C:/Users/HUAWEI/DemoPeter/verify_detail.txt', 'w') as out:
    out.write(f'{"Dir":<30} {"Total":>8} {"git":>8} {"node_mod":>8} {"venv/pyc":>8} {"vendor":>8} {"Real":>8}\n')
    out.write('-' * 80 + '\n')

    for name, d in dirs:
        print(f'Analyzing {name}...', flush=True)
        t, g, n, v, vd, o = count_by_type(d)
        out.write(f'{name:<30} {t:>8,} {g:>8,} {n:>8,} {v:>8,} {vd:>8,} {o:>8,}\n')
        print(f'  Total={t} git={g} node={n} venv={v} vendor={vd} real={o}')

print('Done!')
