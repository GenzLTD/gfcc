import os, sys

def get_dir_size(path):
    total = 0
    count = 0
    errors = 0
    for root, dirs, files in os.walk(path):
        # Skip system/recycle dirs
        dirs[:] = [d for d in dirs if not d.startswith('$') and d != 'System Volume Information']
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
                count += 1
            except (PermissionError, OSError):
                errors += 1
    return total, count, errors

def scan(path, depth=2):
    base = path.rstrip('/').rstrip('\\')
    if not os.path.exists(base):
        print(f"Path not found: {base}")
        return
    
    print(f"\n{'='*60}")
    print(f"  {base}")
    print(f"{'='*60}")
    
    results = []
    try:
        entries = sorted(os.listdir(base))
    except PermissionError:
        print("  Permission denied")
        return
    
    for entry in entries:
        full = os.path.join(base, entry)
        if os.path.isfile(full):
            sz = os.path.getsize(full)
            results.append((entry, sz, 1, 0))
        elif os.path.isdir(full):
            if entry.startswith('$') or entry == 'System Volume Information':
                continue
            sz, cnt, err = get_dir_size(full)
            results.append((entry, sz, cnt, err))
        else:
            results.append((entry, 0, 0, 0))
    
    results.sort(key=lambda x: x[1], reverse=True)
    
    total_all = 0
    for name, size, count, errors in results:
        total_all += size
        gb = size / (1024**3)
        mb = size / (1024**2)
        kb = size / 1024
        if gb >= 0.1:
            flag = f" ({errors} errs)" if errors else ""
            print(f"  {gb:7.2f} GB  {mb:8.0f} MB  {count:6} files  {name}{flag}")
        elif mb >= 0.1:
            print(f"  {gb:7.2f} GB  {mb:8.0f} MB  {count:6} files  {name}")
        elif size > 0:
            print(f"  {gb:7.2f} GB  {kb:8.0f} KB  {count:6} files  {name}")
        else:
            print(f"  {gb:7.2f} GB  {'-':>8}      {count:6} files  {name} (empty)")
    
    print(f"{'='*60}")
    print(f"  合计: {total_all/(1024**3):.2f} GB  ({total_all/(1024**2):.0f} MB)")
    return total_all

# Scan E: root
e_total = scan('E:/', depth=1)

# Scan kb-backup deeper
scan('E:/kb-backup', depth=1)
