with open('backend/api/router.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    if 'async def auto_join_elite():' in line:
        new_lines.append(line)
        i += 1
        # copy until return res
        while i < len(lines) and 'return res' not in lines[i]:
            new_lines.append(lines[i])
            i += 1
        if i < len(lines) and 'return res' in lines[i]:
            new_lines.append(lines[i])
            i += 1
            new_lines.append('        except Exception as e:\n')
            new_lines.append('            raise HTTPException(\n')
            new_lines.append('                status_code=500,\n')
            new_lines.append('                detail=make_error_response("AUTO_JOIN_FAILED", str(e)),\n')
            new_lines.append('            )\n')
            continue
    elif 'return res' in line and i + 1 < len(lines) and 'except Exception as e:' in lines[i+1]:
        new_lines.append(line)
        i += 6 # skip the misplaced except block
        continue
    else:
        new_lines.append(line)
        i += 1

with open('backend/api/router.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("ROUTER_SYNTAX_FIXED")

