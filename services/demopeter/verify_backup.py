import os, sys

def count_files(path):
    cnt = 0
    try:
        for r, ds, fs in os.walk(path):
            ds[:] = [d for d in ds if not d.startswith('$')]
            for f in fs:
                try:
                    os.path.getsize(os.path.join(r, f))
                    cnt += 1
                except:
                    pass
    except:
        return -1
    return cnt

dirs_to_check = [
    ('DemoPPI', 'DemoPPI'),
    ('surface-zervi/GitHub', 'surface-zervi/GitHub'),
    ('surface-zervi/gitea-repos', 'surface-zervi/gitea-repos'),
    ('Nezha', 'Nezha'),
    ('zervi', 'zervi'),
    ('genzltd', 'genzltd'),
    ('go-zervi', 'go-zervi'),
    ('looma', 'looma'),
    ('kungfu-main', 'kungfu-main'),
    ('kung-fu-main', 'kung-fu-main'),
    ('Jobfirst', 'Jobfirst'),
    ('JobfirstClaw', 'JobfirstClaw'),
    ('jobfirst-claw', 'jobfirst-claw'),
    ('gitea_backup', 'gitea_backup'),
    ('Markdowns', 'Markdowns'),
    ('ollama-models', 'ollama-models'),
    ('Downloads', 'Downloads'),
    ('Ctrl4U', 'Ctrl4U'),
    ('Ctrl4U-Rings', 'Ctrl4U-Rings'),
    ('wordpress-plugin', 'wordpress-plugin'),
    ('poetry-knowledge-base', 'poetry-knowledge-base'),
    ('MacSzjason72', 'MacSzjason72'),
]

with open('C:/Users/HUAWEI/DemoPeter/verify_result.txt', 'w', encoding='utf-8') as out:
    out.write(f'{"Dir":<30} {"D-files":>10} {"E-files":>10} {"Match":>8}\n')
    out.write('-' * 62 + '\n')
    
    total_d = total_e = 0
    ok = fail = 0
    fail_names = []
    
    for d_name, d_path in dirs_to_check:
        src = os.path.join('D:/', d_path)
        dst = os.path.join('E:/D-Backup-2026-06-15', d_path)
        
        if not os.path.isdir(src):
            out.write(f'{d_name:<30} {"(missing)":>10} {"-":>10} {"-":>8}\n')
            continue
        
        sys.stdout.write(f'Scanning {d_name}...')
        sys.stdout.flush()
        dc = count_files(src)
        sys.stdout.write(f' D={dc}')
        sys.stdout.flush()
        ec = count_files(dst)
        sys.stdout.write(f' E={ec}')
        sys.stdout.flush()
        
        total_d += dc
        total_e += ec
        
        if dc == ec:
            ok += 1
            match = "OK"
        else:
            fail += 1
            match = f"DIFF {dc-ec:+d}"
            fail_names.append((d_name, dc, ec))
        
        out.write(f'{d_name:<30} {dc:>10,} {ec:>10,} {match:>8}\n')
        out.flush()
        sys.stdout.write(' -> DONE\n')
        sys.stdout.flush()
    
    out.write('-' * 62 + '\n')
    out.write(f'{"TOTAL":<30} {total_d:>10,} {total_e:>10,}\n')
    out.write(f'\nOK: {ok}  DIFF: {fail}\n')
    if fail_names:
        out.write('Diff details:\n')
        for name, dc, ec in fail_names:
            pct = abs(dc-ec)/dc*100 if dc else 0
            out.write(f'  {name}: D={dc} E={ec} (diff {dc-ec:+d}, {pct:.1f}%)\n')
    
    sys.stdout.write('\nDone!\n')
