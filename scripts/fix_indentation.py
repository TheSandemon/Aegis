import glob
import os

files = glob.glob('aegis_data/**/worker.py', recursive=True)
count = 0
for f in files:
    with open(f, 'r', encoding='utf-8') as file:
        lines = file.readlines()
    
    changed = False
    for i, line in enumerate(lines):
        # We look for the exact comment that starts the block
        if "Check if agent is assigned to a specific card" in line and line.startswith("        # "):
            # Fix indentation of this block
            # Deduct 4 spaces from the start of every line from here to the end of the block
            j = i
            while j < len(lines):
                # The block ends when we encounter a line with 4 spaces or less, empty lines are fine
                if len(lines[j]) > 4 and lines[j].startswith("        "):
                    lines[j] = lines[j][4:]
                    changed = True
                elif lines[j].strip() == "":
                    pass
                elif len(lines[j]) > 0 and not lines[j].startswith("     "):
                    break # end of block
                j += 1
            break
            
    if changed:
        with open(f, 'w', encoding='utf-8') as file:
            file.writelines(lines)
        print(f"Fixed {f}")
        count += 1
print(f"Fixed {count} files")
