##!/usr/bin/env python3

import re
import sys
import os
import subprocess
import json
import time
import math
import glob
import shutil
import hashlib
from collections import defaultdict, deque
from itertools import product

# --- Helper Functions for DOT Processing ---

def parse_dot_content(content):
    nodes = {}
    edges = []
    for m in re.finditer(r'"([^"]+)"\s*\[([^\]]+)\];', content):
        nodes[m.group(1)] = m.group(2).strip()
    for m in re.finditer(r'"([^"]+)"\s*->\s*"([^"]+)";', content):
        edges.append((m.group(1), m.group(2)))
    return nodes, edges


def generate_llvm_ir_from_binary(binary_path: str, output_ll_path: str = None, timeout: int = 600) -> str:

    retdec_path = '/media/sf_Test_result/retdec/bin/retdec-decompiler.py'
    
    if not os.path.exists(retdec_path):
        print(f"[ERROR] retdec-decompiler not found at: {retdec_path}")
        return None
    
    if not os.path.exists(binary_path):
        print(f"[ERROR] Binary file not found: {binary_path}")
        return None
    
    binary_path = os.path.abspath(binary_path)
    binary_name = os.path.basename(binary_path)  # Например: "libc.so.6" или "aa-enabled"
    
    # Определяем рабочую директорию
    if output_ll_path and os.path.isdir(output_ll_path):
        work_dir = os.path.abspath(output_ll_path)
    else:
        work_dir = os.path.dirname(binary_path)
    
    # Имена файлов без всяких хешей и суффиксов
    output_c = binary_name + '.c'
    expected_ll = os.path.join(work_dir, binary_name + '.ll')
    
    # === ПРОСТАЯ ПРОВЕРКА КЕША ===
    if os.path.exists(expected_ll) and os.path.getsize(expected_ll) > 100:
        print(f"[INFO] Using CACHED LLVM IR: {binary_name}.ll")
        return expected_ll
    
    cmd = [retdec_path, binary_path, '--output', output_c]
    
    print(f"[INFO] Generating LLVM IR: {binary_name}")
    print(f"[INFO] Working directory: {work_dir}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir
        )
        
        if result.returncode != 0:
            print(f"[WARN] retdec-decompiler finished with code {result.returncode}")
        
        if not os.path.exists(expected_ll):
            print(f"[ERROR] No .ll file generated")
            return None
        
        print(f"[INFO] Cleaning up: keeping only {binary_name}.ll")
        
        for f in os.listdir(work_dir):
            full_path = os.path.join(work_dir, f)
            if not os.path.isfile(full_path):
                continue
            if full_path == expected_ll:
                continue
            if f.startswith(binary_name):
                try:
                    os.remove(full_path)
                except Exception:
                    pass
        
        print(f"[SUCCESS] LLVM IR generated: {expected_ll}")
        return expected_ll
        
    except subprocess.TimeoutExpired:
        print(f"[ERROR] Timeout ({timeout}s) while running retdec-decompiler")
        return None
    except Exception as e:
        print(f"[ERROR] Exception during IR generation: {type(e).__name__}: {e}")
        return None


def generate_simplified_and_verified_graphs(merged_dot_path, bridge_func, stack_funcs=[], 
                                            output_simplified="simplified_graph.dot", 
                                            output_verified="verified_stack.dot"):
    if not os.path.exists(merged_dot_path):
        print(f"[ERROR] Merged DOT file {merged_dot_path} not found."); return

    with open(merged_dot_path, 'r') as f:
        content = f.read()
    
    all_nodes, all_edges = parse_dot_content(content)
    graph = defaultdict(list)
    for u, v in all_edges:
        graph[u].append(v)
    
    # 1. Путь от @main до моста
    path_to_bridge_nodes = set()
    path_to_bridge_edges = set()
    q = deque([("@main", ["@main"])])
    visited = set()
    bridge_path_found = False
    
    while q:
        curr, path = q.popleft()
        if curr in visited: continue
        visited.add(curr)
        
        if curr == bridge_func:
            bridge_path_found = True
            for i in range(len(path)-1):
                u, v = path[i], path[i+1]
                path_to_bridge_edges.add((u, v))
                path_to_bridge_nodes.add(u)
                path_to_bridge_nodes.add(v)
            break
        
        for neighbor in graph[curr]:
            if neighbor not in visited:
                q.append((neighbor, path + [neighbor]))
    
    if not bridge_path_found:
        path_to_bridge_nodes = set(all_nodes.keys())
        path_to_bridge_edges = set(all_edges)

    library_nodes = set()
    library_edges = set()
    q_lib = deque([bridge_func])
    visited_lib = {bridge_func}
    
    while q_lib:
        curr = q_lib.popleft()
        library_nodes.add(curr)
        for neighbor in graph[curr]:
            if neighbor not in visited_lib:
                visited_lib.add(neighbor)
                library_edges.add((curr, neighbor))
                q_lib.append(neighbor)
    
    final_nodes = path_to_bridge_nodes.union(library_nodes)
    final_edges = path_to_bridge_edges.union(library_edges)
    final_edges_filtered = {(u, v) for u, v in final_edges if u in final_nodes and v in final_nodes}
    
    with open(output_verified, 'w') as f:
        f.write('digraph CallGraph {\n')
        f.write('  rankdir=TB;\n')
        f.write('  node [shape=box, style=filled, fontname="Arial", fontsize=10];\n')
        
        highlighted = []
        for node in sorted(final_nodes):
            if node in all_nodes:
                attrs = all_nodes[node]
                
                if node in stack_funcs:
                    attrs = re.sub(r',?\s*fillcolor="#[a-fA-F0-9]+"', '', attrs)
                    attrs = attrs.strip().strip(',').strip()
                    
                    if attrs:
                        f.write(f'  "{node}" [{attrs}, fillcolor="#90EE90"];\n')
                    else:
                        f.write(f'  "{node}" [fillcolor="#90EE90"];\n')
                        
                    highlighted.append(node.lstrip('@'))
                else:
                    f.write(f'  "{node}" [{attrs}];\n')
        
        for src, dst in sorted(final_edges_filtered):
            f.write(f'  "{src}" -> "{dst}";\n')
        
        f.write('}\n')
    
    print(f"[INFO] Verified stack graph saved: {output_verified}")
    if highlighted:
        print(f"[INFO] Highlighted functions (Green): {', '.join(sorted(list(highlighted)))}")
    else:
        print("[WARN] No stack functions found in graph to highlight.")


def generate_reachability_path_dot(merged_dot_path: str, target_func: str, 
                                   root_func: str = "@main",
                                   output_path: str = "reachability_path.dot"):

    if not os.path.exists(merged_dot_path):
        print(f"[ERROR] Merged DOT file not found: {merged_dot_path}"); return False
    
    nodes, edges = parse_dot_content(open(merged_dot_path, 'r').read())
    
    graph = defaultdict(list)
    for u, v in edges:
        graph[u].append(v)
    
    if root_func not in nodes:
        print(f"[WARN] Root function {root_func} not found in graph")
        return False
    if target_func not in nodes:
        print(f"[WARN] Target function {target_func} not found in graph")
        return False
    
    q = deque([(root_func, [root_func])])
    visited = {root_func}
    path_found = None
    
    while q:
        curr, path = q.popleft()
        if curr == target_func:
            path_found = path
            break
        for neighbor in graph[curr]:
            if neighbor not in visited:
                visited.add(neighbor)
                q.append((neighbor, path + [neighbor]))
    
    if not path_found:
        print(f"[WARN] No path found from {root_func} to {target_func}")
        return False
    
    path_edges = [(path_found[i], path_found[i+1]) for i in range(len(path_found)-1)]
    path_nodes = set(path_found)
    
    with open(output_path, 'w') as f:
        f.write('digraph ReachabilityPath {\n')
        f.write('  rankdir=TB;\n')
        f.write('  node [shape=box, style=filled, fontname="Arial", fontsize=10];\n')
        f.write('  edge [color="#666666", fontsize=8];\n')
        
        for node in path_nodes:
            attrs = nodes.get(node, 'label=""')
            attrs = re.sub(r',?\s*fillcolor="#[a-fA-F0-9]+"', '', attrs).strip().strip(',')
            
            if node == target_func:
                attrs = f'{attrs}, fillcolor="#00FF00", penwidth=2.5, color="#00AA00"' if attrs else 'fillcolor="#00FF00", penwidth=2.5, color="#00AA00"'
            elif node == root_func:
                attrs = f'{attrs}, fillcolor="#FFFF99"' if attrs else 'fillcolor="#FFFF99"'
            else:
                attrs = f'{attrs}, fillcolor="#90EE90"' if attrs else 'fillcolor="#90EE90"'
            
            f.write(f'  "{node}" [{attrs}];\n')
        
        for src, dst in path_edges:
            f.write(f'  "{src}" -> "{dst}" [color="#FF0000", penwidth=2, arrowsize=1.2];\n')
        
        f.write('}\n')
    
    print(f"[SUCCESS] Reachability path saved: {output_path}")
    print(f"[INFO] Path length: {len(path_found)} functions")
    print(f"[INFO] Path: {' -> '.join(f.lstrip('@') for f in path_found)}")
    return True


def extract_stack_functions(log_filepath):
    """Извлекает список функций из лога верификации (STACK секция) и добавляет @."""
    try:
        with open(log_filepath, 'r') as f:
            content = f.read()
        
        stack_match = re.search(r'\[STACK\](.+?)(?=\n=== END|\n\[LEAVE\]|\Z)', content, re.DOTALL)
        if not stack_match:
            return set()
            
        stack_text = stack_match.group(1)
        funcs = set()
        
        pattern = re.compile(r'!\s*([a-zA-Z_]\w+)(?:\+0x[0-9a-fA-F]+)?')
        
        for match in pattern.finditer(stack_text):
            func_name = match.group(1)
            funcs.add("@" + func_name)
            
        return funcs
    except Exception:
        return set()

def apply_replacements_to_call_map(call_map: dict, replacements: dict) -> dict:
    from collections import defaultdict
    new_call_map = defaultdict(set)
    for caller, callees in call_map.items():
        resolved_caller = resolve_chain(caller, replacements)
        for callee in callees:
            resolved_callee = resolve_chain(callee, replacements)
            if resolved_callee != resolved_caller:
                new_call_map[resolved_caller].add(resolved_callee)
    return dict(new_call_map)


def apply_replacements_to_func_logic(func_logic: dict, replacements: dict) -> dict:
    new_func_logic = {}
    for func, logic in func_logic.items():
        resolved = resolve_chain(func, replacements)
        if resolved not in new_func_logic:
            new_func_logic[resolved] = {
                "globals": set(logic.get("globals", [])),
                "calls": set(logic.get("calls", [])),
                "entry_block": logic.get("entry_block"),
                "indirect_regs": set(logic.get("indirect_regs", []))
            }
        else:
            new_func_logic[resolved]["globals"].update(logic.get("globals", []))
            new_func_logic[resolved]["calls"].update(logic.get("calls", []))
            if not new_func_logic[resolved]["entry_block"] and logic.get("entry_block"):
                new_func_logic[resolved]["entry_block"] = logic["entry_block"]
            new_func_logic[resolved]["indirect_regs"].update(logic.get("indirect_regs", []))
    return new_func_logic


try:
    import frida
except ImportError:
    print("[WARNING] frida Python module not found. Verification will be disabled.")
    print("Install via: pip install frida-tools\n")
    frida = None

def extract_strings_and_envs(ir_path: str):
    with open(ir_path, 'r', encoding='utf-8', errors='ignore') as f:
        ir_content = f.read()

    all_strings = {}
    str_pattern = re.compile(
        r'(@global_var_\w+)\s*=\s*(?:local_unnamed_addr\s+)?constant\s+'
        r'\[\d+\s+x\s+i8\]\s+c"((?:[^"\\]|\\.)*)\\00"'
    )
    for match in str_pattern.finditer(ir_content):
        gvar, s_val = match.group(1), match.group(2)
        s_val = (s_val.replace('\\0A', '\n').replace('\\0D', '\r')
                 .replace('\\00', '').replace('\\\\', '\\'))
        if len(s_val) >= 2 and not s_val.startswith('(null)') and not s_val.startswith('['):
            all_strings[gvar] = s_val

    env_vars = []
    for line in ir_content.split('\n'):
        if '@getenv' in line:
            for gvar, s_val in all_strings.items():
                if gvar in line and s_val not in env_vars:
                    env_vars.append(s_val)
                    break

    candidate_values = set()
    strstr_pattern = re.compile(r'@strstr.*?(@global_var_\w+)')
    for match in strstr_pattern.finditer(ir_content):
        gvar = match.group(1)
        if gvar in all_strings:
            candidate_values.add(all_strings[gvar])

    env_values = {}
    for env in env_vars:
        vals = list(candidate_values)
        vals.append(None)
        env_values[env] = vals

    return env_vars, env_values


def generate_frida_hook(target_func: str, env_vars: list) -> str:
    env_list_json = json.dumps(env_vars)
    return f'''// Automatically generated by unified_analyzer.py
const TARGET_NAME = "{target_func}";
const ENV_VARS = {env_list_json};

console.log(`[Frida] Hooking ${{TARGET_NAME}}...`);

const sym = DebugSymbol.fromName(TARGET_NAME);
if (sym.address === null || sym.address.isNull()) {{
    console.error(`[ERROR] ${{TARGET_NAME}} not found`);
    send({{type: 'error', payload: `[ERROR] ${{TARGET_NAME}} not found`}});
}} else {{
    console.log(`[SUCCESS] Found ${{TARGET_NAME}} @ ${{sym.address}}`);
    send({{type: 'info', payload: `[SUCCESS] Found ${{TARGET_NAME}} @ ${{sym.address}}`}});
    
    Interceptor.attach(sym.address, {{
        onEnter: function(args) {{
            console.log(`\\n=== HIT ${{TARGET_NAME}} ===`);
            console.log(`[TRIGGERED] Function is reachable!`);
            
            send({{type: 'triggered', payload: {{
                function: TARGET_NAME,
                address: sym.address.toString(),
                timestamp: Date.now()
            }}}});
            
            try {{
                const libc = Process.getModuleByName("libc.so.6") || Process.getModuleByName("libc.so");
                if (libc) {{
                    const getenvPtr = libc.getExportByName("getenv");
                    if (getenvPtr && !getenvPtr.isNull()) {{
                        const getenv = new NativeFunction(getenvPtr, "pointer", ["pointer"]);
                        for (const envName of ENV_VARS) {{
                            try {{
                                const envVal = getenv(Memory.allocUtf8String(envName));
                                const valStr = envVal.isNull() ? "(null)" : envVal.readUtf8String();
                                console.log(`  ENV ${{envName}}: ${{valStr}}`);
                                send({{type: 'env', payload: {{name: envName, value: valStr}}}});
                            }} catch(e) {{}}
                        }}
                    }}
                }}
            }} catch(e) {{}}
            
            try {{
                const stack = Thread.backtrace(this.context, Backtracer.ACCURATE)
                    .map(DebugSymbol.fromAddress).join('\\n\\t');
                console.log(`[STACK] ${{stack}}`);
                send({{type: 'stack', payload: stack}});
            }} catch(e) {{}}
            
            console.log(`=== END ${{TARGET_NAME}} ===\\n`);
            if (console.flush) console.flush();
        }},
        onLeave: function(retval) {{
            console.log(`[LEAVE] ${{TARGET_NAME}} returned: ${{retval}}`);
            send({{type: 'leave', payload: {{retval: retval.toString()}}}});
            if (console.flush) console.flush();
        }}
    }});
    console.log("[INFO] Hook installed. Waiting for execution...");
    send({{type: 'info', payload: "[INFO] Hook installed. Waiting for execution..."}});
}}
'''


def run_fuzz_combination_api(binary_path: str, hook_script: str, env_combo: dict, timeout: int = 15) -> tuple:
    if frida is None:
        return False, "[ERROR] Frida module not available"
    
    logs = []
    triggered = False
    script = None
    session = None
    
    def on_message(message, data):
        nonlocal triggered
        msg_type = message.get('type', 'unknown')
        if msg_type == 'send':
            payload = message.get('payload', {})
            ptype = payload.get('type') if isinstance(payload, dict) else None
            if ptype == 'triggered':
                triggered = True
                logs.append(f"[TRIGGERED] {json.dumps(payload)}")
            elif ptype == 'env':
                logs.append(f"[ENV] {payload.get('name')}={payload.get('value')}")
            elif ptype == 'stack':
                logs.append(f"[STACK]\n{payload}")
            elif ptype == 'leave':
                logs.append(f"[LEAVE] retval={payload.get('retval')}")
            elif isinstance(payload, str):
                logs.append(payload)
        elif msg_type == 'error':
            logs.append(f"[FRIDA ERROR] {message.get('description', 'unknown error')}")
        else:
            logs.append(f"[{msg_type}] {json.dumps(message, default=str)}")
    
    try:
        device = frida.get_local_device()
        env = os.environ.copy()
        for var_name, var_value in env_combo.items():
            if var_value is None:
                env.pop(var_name, None)
            else:
                env[var_name] = str(var_value)
        
        pid = device.spawn([binary_path], env=env, stdio='pipe')
        session = device.attach(pid)
        script = session.create_script(hook_script)
        script.on('message', on_message)
        script.load()
        device.resume(pid)
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            if session.is_detached:
                break
            time.sleep(0.1)
        time.sleep(0.5)
        
    except frida.ServerNotRunningError:
        logs.append("[ERROR] Frida server is not running")
    except frida.ProcessNotFoundError:
        logs.append(f"[ERROR] Process not found: {binary_path}")
    except Exception as e:
        logs.append(f"[ERROR] {type(e).__name__}: {e}")
    finally:
        if script:
            try: script.unload()
            except: pass
        if session:
            try: session.detach()
            except: pass
    
    return triggered, '\n'.join(logs)


def run_verification_step(target_func: str, ir_path: str, binary_path: str, timeout: int = 15) -> bool:
    print(f"\n[INFO] Starting verification for @{target_func}...")
    
    if not os.path.exists(ir_path) or not os.path.exists(binary_path):
        print("[ERROR] File not found"); return False
    if frida is None:
        print("[ERROR] Frida module not available"); return False

    print(f"   [1] Analyzing {os.path.basename(ir_path)}...")
    env_vars, env_values = extract_strings_and_envs(ir_path)
    
    if not env_vars:
        print("   [WARN] No ENV variables found. Skipping fuzzing."); return False
    
    print(f"   [INFO] Found {len(env_vars)} ENV variable(s): {env_vars}")
    for env, vals in env_values.items():
        display = [v if v is not None else "<UNSET>" for v in vals]
        print(f"      - {env}: {display}")

    hook_content = generate_frida_hook(target_func, env_vars)
    success_log = f"{target_func}_verification.log"
    all_log = f"{target_func}_fuzz.log"
    open(success_log, 'w').close()
    open(all_log, 'w').close()

    print(f"   [2] Starting ENV fuzzing...")
    combo_lists = [[(var, val) for val in env_values.get(var, [None])] for var in env_vars]
    tested = success_count = 0

    for combo_items in product(*combo_lists):
        combo = dict(combo_items)
        tested += 1
        combo_str = " ".join([f"{k}='{v}'" if v is not None else f"{k}=<UNSET>" for k, v in combo.items()])
        print(f"      [{tested}] Testing: {combo_str}")
        
        triggered, output = run_fuzz_combination_api(binary_path, hook_content, combo, timeout)
        
        with open(all_log, 'a') as f:
            f.write(f"\n--- Test #{tested}: {combo_str} ---\n{output[:2000]}\n")
        
        if triggered:
            success_count += 1
            print(f"         [SUCCESS] Triggered!")
            with open(success_log, 'a') as f:
                f.write(f"\n=== SUCCESS #{success_count} ===\nENV: {combo_str}\n{output}\n{'='*40}\n")
        else:
            print(f"         [FAIL] Not triggered")

    print(f"\n   [INFO] Verification complete: {success_count}/{tested} successful")
    if success_count > 0:
        print(f"   [INFO] Successful combinations saved to: {success_log}"); return True
    else:
        print(f"   [WARN] No successful combinations. Check {all_log}"); return False

def find_stubs_and_orphans(call_map, func_logic):
    noise = {"__decompiler_undefined_function_0", "__decompiler_undefined_function_1",
             "__gmon_start__", "__cxa_finalize", "puts", "printf", "system", "getenv", 
             "strncpy", "strstr", "malloc", "free", "memcpy", "memset", "exit", "abort"}
    protected = {"@main", "@_init", "@_fini", "@_start", "@deregister_tm_clones", 
                 "@register_tm_clones", "@frame_dummy", "@__do_global_dtors_aux"}

    stubs, orphans = [], []
    all_callees = set(c for calls in call_map.values() for c in calls)

    for func, logic in func_logic.items():
        if func.lstrip('@') in noise or func in protected:
            continue
        calls, gl = logic.get("calls", set()), logic.get("globals", set())
        cplx = len(calls) + len(gl)
        is_stub = func.startswith('@function_') or func.startswith('@sub_')
        
        if is_stub and cplx <= 2 and not (cplx <= 1 and any(c.lstrip('@') in noise for c in calls)):
            stubs.append(func)
        elif not is_stub and cplx > 2 and func not in all_callees:
            orphans.append(func)
    
    return stubs, orphans


def get_function_fingerprint(func, func_logic, call_map):
    logic = func_logic.get(func, {})
    calls = logic.get("calls", set())
    globals_set = logic.get("globals", set())
    
    noise = {"puts", "printf", "system", "getenv", "strncpy", "strstr", 
             "malloc", "free", "memcpy", "memset", "exit", "abort", 
             "__libc_start_main", "__cxa_finalize", "__gmon_start__"}
    
    clean_calls = {c for c in calls if c.lstrip('@') not in noise}
    
    return {
        "num_calls": len(calls),
        "num_clean_calls": len(clean_calls),
        "num_globals": len(globals_set),
        "clean_calls": clean_calls,
        "globals": globals_set
    }


def get_neighbors_extended(func, call_map, depth=2):
    neighbors = set()
    queue = deque([(func, 0)])
    visited = {func}
    
    while queue:
        curr, d = queue.popleft()
        if d >= depth:
            continue
        
        for callee in call_map.get(curr, set()):
            if callee not in visited:
                visited.add(callee)
                neighbors.add(callee)
                queue.append((callee, d + 1))
        
        for caller, callees in call_map.items():
            if curr in callees and caller not in visited:
                visited.add(caller)
                neighbors.add(caller)
                queue.append((caller, d + 1))
                
    return neighbors


def heuristic_level_1_address_alignment(call_map: dict, func_logic: dict,
                                        ir_path: str = None, elf_path: str = None) -> dict:
    import re
    
    if not ir_path or not os.path.exists(ir_path):
        return {}
    
    addr_meta = {}
    with open(ir_path, 'r', encoding='utf-8') as f:
        for m in re.finditer(r'!(\d+)\s*=\s*!\{i64\s+(\d+)\}', f.read()):
            addr_meta[f"!{m.group(1)}"] = int(m.group(2))
    
    func_starts = {}
    with open(ir_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    func_pattern = re.compile(r'^define\s+[^@]*?@(\w+)\s*\(')
    addr_ref = re.compile(r'!insn\.addr\s+!(\d+)')
    
    current = None
    for line in content.split('\n'):
        if (m := func_pattern.match(line.strip())):
            current = "@" + m.group(1)
            continue
        if current and current not in func_starts and (m := addr_ref.search(line)):
            key = f"!{m.group(1)}"
            if key in addr_meta:
                func_starts[current] = addr_meta[key]
    
    stubs, orphans = find_stubs_and_orphans(call_map, func_logic)
    replacements = {}
    used = set()
    
    for stub in stubs:
        s_addr = func_starts.get(stub)
        if s_addr is None: continue
        
        best, min_diff = None, float('inf')
        for orphan in orphans:
            if orphan in used: continue
            o_addr = func_starts.get(orphan)
            if o_addr is None: continue
            
            diff = abs(s_addr - o_addr)
            if diff < min_diff:
                min_diff = diff
                best = orphan
        
        if best and min_diff < 512:
            replacements[stub] = best
            used.add(best)
            print(f"[Method 1] Matched {stub} -> {best} (addr_diff: {min_diff})")
    
    return replacements


def heuristic_level_2_arg_dataflow(call_map: dict, func_logic: dict,
                                   ir_path: str = None, elf_path: str = None) -> dict:
    import re
    
    if not ir_path or not os.path.exists(ir_path):
        return {}
    
    with open(ir_path, 'r', encoding='utf-8') as f:
        ir_content = f.read()
    
    def get_stub_arg_type(func_name: str) -> str:
        pattern = rf'define\s+\S+\s+@{re.escape(func_name.lstrip("@"))}\s*\(([^)]*)\)'
        match = re.search(pattern, ir_content)
        if not match or not match.group(1).strip():
            return 'none'
        first_arg = match.group(1).split(',')[0].strip()
        return 'pointer' if '*' in first_arg else 'value'
    
    def get_dataflow_profile(func_name: str) -> dict:
        pattern = rf'define\s+[^{{]*@{re.escape(func_name.lstrip("@"))}[^{{]*\{{(.*?)^}}'
        match = re.search(pattern, ir_content, re.MULTILINE | re.DOTALL)
        if not match:
            return {'ptr': 0, 'val': 0}
        
        body = match.group(1)
        ptr_ops = len(re.findall(r'\b(getelementptr|load|store|icmp\s+eq\s+i8\*)\b', body, re.IGNORECASE))
        val_ops = len(re.findall(r'\b(select|br\s+i1|icmp\s+eq\s+i[0-9]+|add|sub|mul|shl|and|or|xor)\b', body, re.IGNORECASE))
        return {'ptr': ptr_ops, 'val': val_ops}
    
    stubs, orphans = find_stubs_and_orphans(call_map, func_logic)
    
    stub_info = {s: get_stub_arg_type(s) for s in stubs}
    orphan_info = {o: get_dataflow_profile(o) for o in orphans}
    
    replacements = {}
    used_orphans = set()
    
    for stub, stype in stub_info.items():
        if stype == 'none' or stub in replacements:
            continue
            
        best, best_score = None, -1
        for orphan in orphans:
            if orphan in used_orphans:
                continue
                
            p_ops = orphan_info.get(orphan, {}).get('ptr', 0)
            v_ops = orphan_info.get(orphan, {}).get('val', 0)
            
            if stype == 'pointer':
                score = p_ops - v_ops
            else:
                score = v_ops - p_ops
                
            if score > best_score:
                best_score = score
                best = orphan
        
        if best and best_score > 0:
            replacements[stub] = best
            used_orphans.add(best)
            print(f"[Method 2] Matched {stub} -> {best} ({stype}_arg aligned with dataflow profile)")
    
    remaining_stubs = [s for s in stubs if s not in replacements]
    remaining_orphans = [o for o in orphans if o not in used_orphans]
    
    if remaining_stubs and remaining_orphans:
        addr_meta = {}
        for m in re.finditer(r'!(\d+)\s*=\s*!\{i64\s+(\d+)\}', ir_content):
            addr_meta[f"!{m.group(1)}"] = int(m.group(2))
            
        func_starts = {}
        current = None
        addr_ref = re.compile(r'!insn\.addr\s+!(\d+)')
        for line in ir_content.split('\n'):
            if (m := re.match(r'^define\s+[^@]*?@(\w+)\s*\(', line.strip())):
                current = "@" + m.group(1)
            if current and current not in func_starts and (m := addr_ref.search(line)):
                key = f"!{m.group(1)}"
                if key in addr_meta:
                    func_starts[current] = addr_meta[key]
                    
        for stub in remaining_stubs:
            s_addr = func_starts.get(stub, 0)
            best, min_diff = None, float('inf')
            
            for orphan in orphans:
                if orphan in used_orphans:
                    continue
                o_addr = func_starts.get(orphan, 0)
                diff = abs(s_addr - o_addr)
                if diff < min_diff:
                    min_diff = diff
                    best = orphan
                    
            if best:
                replacements[stub] = best
                used_orphans.add(best)
                
    if replacements:
        print(f"[Method 2] Finalized {len(replacements)} matches via arg/dataflow alignment")
    return replacements


def heuristic_level_3_complexity(call_map, func_logic):
    stubs, orphans = find_stubs_and_orphans(call_map, func_logic)
    replacements = {}
    
    orphans.sort(key=lambda f: len(func_logic[f].get("calls",[])) + len(func_logic[f].get("globals",[])), reverse=True)
    
    def stub_priority(s):
        return max((len(func_logic.get(caller, {}).get("calls", [])) for caller, callees in call_map.items() if s in callees), default=0)
    stubs.sort(key=stub_priority, reverse=True)
    
    used = set()
    for stub in stubs:
        for o in orphans:
            if o not in used:
                replacements[stub] = o
                used.add(o)
                break
    
    return replacements


def heuristic_level_4_stochastic(call_map: dict, func_logic: dict,
                                  ir_path: str = None, elf_path: str = None) -> dict:
    import random
    
    stubs, orphans = find_stubs_and_orphans(call_map, func_logic)
    if not stubs or not orphans:
        return {}
    
    def random_score(func):
        logic = func_logic.get(func, {})
        w_calls = random.uniform(0.5, 2.0)
        w_globals = random.uniform(0.3, 1.5)
        w_strings = random.uniform(0.0, 3.0) if ir_path else 0
        
        score = len(logic.get("calls", set())) * w_calls + len(logic.get("globals", set())) * w_globals
        
        if ir_path and w_strings > 0:
            try:
                with open(ir_path) as f:
                    content = f.read()
                func_pat = rf'define[^{{]*@{re.escape(func.lstrip("@"))}'
                if re.search(func_pat, content):
                    str_count = len(re.findall(r'@global_var_\w+', 
                        re.search(rf'{func_pat}[^{{]*\{{(.*?)^}}', content, re.DOTALL)[0] if re.search(rf'{func_pat}[^{{]*\{{(.*?)^}}', content, re.DOTALL) else ''))
                    score += str_count * w_strings
            except: pass
        return score
    
    votes = defaultdict(lambda: defaultdict(int))
    
    for _ in range(100):
        random.seed(_)
        
        stubs_shuffled = stubs.copy()
        orphans_shuffled = orphans.copy()
        random.shuffle(stubs_shuffled)
        random.shuffle(orphans_shuffled)
        
        used = set()
        for stub in stubs_shuffled:
            candidates = [(o, random_score(o)) for o in orphans_shuffled if o not in used]
            if candidates:
                best = max(candidates, key=lambda x: x[1])[0]
                votes[stub][best] += 1
                used.add(best)
    
    replacements = {}
    for stub in stubs:
        if votes[stub]:
            best, count = max(votes[stub].items(), key=lambda x: x[1])
            if count >= 30:
                replacements[stub] = best
    
    if replacements:
        print(f"[Method 4] Matched {len(replacements)} functions via stochastic voting (consensus >=30%)")
    return replacements


def heuristic_level_5_libc_role(call_map: dict, func_logic: dict,
                                ir_path: str = None, elf_path: str = None) -> dict:
    API_CATS = {
        'env': {'getenv', 'secure_getenv'},
        'str': {'strlen', 'strcpy', 'strncpy', 'strcmp', 'strstr', 'strcat'},
        'io': {'printf', 'fprintf', 'puts', 'fputs', 'scanf'},
        'mem': {'malloc', 'calloc', 'realloc', 'free', 'memcpy', 'memset'},
        'exec': {'system', 'execve', 'popen', 'posix_spawn'},
        'net': {'socket', 'connect', 'bind', 'send', 'recv'},
    }
    
    def get_api_profile(func):
        calls = func_logic.get(func, {}).get("calls", set())
        profile = set()
        for c in calls:
            name = c.lstrip('@').lower()
            for cat, patterns in API_CATS.items():
                if any(p in name for p in patterns):
                    profile.add(cat)
                    break
        return profile
    
    stubs, orphans = find_stubs_and_orphans(call_map, func_logic)
    
    replacements = {}
    used = set()
    
    for stub in stubs:
        s_profile = get_api_profile(stub)
        if not s_profile:
            for caller, callees in call_map.items():
                if stub in callees:
                    s_profile = get_api_profile(caller)
                    break
        
        if not s_profile: continue
        
        best, best_overlap = None, 0
        for orphan in orphans:
            if orphan in used: continue
            o_profile = get_api_profile(orphan)
            
            if not o_profile: continue
            overlap = len(s_profile & o_profile) / len(s_profile | o_profile)
            
            if overlap > best_overlap:
                best_overlap = overlap
                best = orphan
        
        if best and best_overlap > 0.5:
            replacements[stub] = best
            used.add(best)
            print(f"[Method 5] Matched {stub} -> {best} (api_jaccard: {best_overlap:.2f})")
    
    return replacements


def run_multi_level_resolution(call_map, func_logic, ir_path=None, elf_path=None):
    print("\n[INFO] Running Multi-Level Heuristic Analysis...")
    
    results = {}
    results[1] = heuristic_level_1_address_alignment(call_map, func_logic, ir_path, elf_path)
    results[2] = heuristic_level_2_arg_dataflow(call_map, func_logic, ir_path, elf_path)
    results[3] = heuristic_level_3_complexity(call_map, func_logic)
    results[4] = heuristic_level_4_stochastic(call_map, func_logic, ir_path, elf_path)
    results[5] = heuristic_level_5_libc_role(call_map, func_logic, ir_path, elf_path)

    print("\n=== HEURISTIC ANALYSIS RESULTS ===")
    for level in [1, 2, 3, 4, 5]:
        print(f"\n[Level {level}] Resolution:")
        reps = results.get(level, {})
        if not reps:
            print("   No matches found.")
        else:
            for stub, orphan in reps.items():
                print(f"   {stub} -> {orphan}")
    
    print("\n==================================")
    
    # Автоматически выбираем лучший метод (по количеству совпадений)
    best_level = max(results.keys(), key=lambda l: len(results[l]))
    print(f"\n[AUTO] Selected Level {best_level} with {len(results[best_level])} matches")
    return results[best_level]


def parse_llvm_ir(filepath: str) -> tuple:
    call_map, func_logic = defaultdict(set), {}
    func_re = re.compile(r'^define\s+[^@]*?@(\w+)\s*\(')
    block_re = re.compile(r'^(\w+):')
    
    call_patterns = [
        r'call\s+(?:[^@\n]*?)@([a-zA-Z_]\w+)\s*\(',
        r'invoke\s+(?:[^@\n]*?)@([a-zA-Z_]\w+)\s*\(',
        r'tail\s+call\s+(?:[^@\n]*?)@([a-zA-Z_]\w+)\s*\(',
        r'call\s+i\d+\s+(?:[a-z_]+\s+)*@([a-zA-Z_]\w+)\s*\(',
        r'call\s+void\s+(?:[a-z_]+\s+)*@([a-zA-Z_]\w+)\s*\(',
    ]
    
    global_ref_re = re.compile(r'(@global_var_\w+)')
    indirect_call_re = re.compile(r'(?:call|invoke|tail)\s+i64\s+%(\w+)\s*\(')

    current_func = current_block = entry_block = None
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith((';', '!', 'uselistorder')):
                continue
            if (m := func_re.match(stripped)):
                current_func = "@" + m.group(1)
                entry_block = current_block = None
                func_logic[current_func] = {"globals": set(), "calls": set(), "entry_block": None}
                continue
            if current_func:
                if stripped == '}':
                    current_func = None; continue
                if (m := block_re.match(stripped)):
                    if current_block is None:
                        entry_block = m.group(1)
                        func_logic[current_func]["entry_block"] = entry_block
                    current_block = m.group(1); continue
                if current_block is not None:
                    func_logic[current_func]["globals"].update(global_ref_re.findall(stripped))
                    for pattern in call_patterns:
                        for c_match in re.finditer(pattern, stripped):
                            callee = "@" + c_match.group(1)
                            if not callee.startswith("@global_var_"):
                                call_map[current_func].add(callee)
                                func_logic[current_func]["calls"].add(callee)
                    for ic_match in indirect_call_re.finditer(stripped):
                        func_logic[current_func].setdefault("indirect_regs", set()).add(ic_match.group(1))
    return dict(call_map), func_logic


def parse_rules(filepath: str) -> tuple:
    root, replacements = None, {}
    with open(filepath, 'r') as f:
        lines = [l.strip() for l in f if l.strip()]
        if not lines: raise ValueError("Rules file is empty")
        root = lines[0] if lines[0].startswith("@") else "@" + lines[0]
        for line in lines[1:]:
            if '=' in line:
                old, new = [s.strip() for s in line.split('=', 1)]
                replacements[old if old.startswith("@") else "@"+old] = new if new.startswith("@") else "@"+new
    return root, replacements


try:
    from elftools.elf.elffile import ELFFile
except ImportError:
    ELFFile = None


class ELFRelocResolver:
    def __init__(self, elf_path):
        if ELFFile is None: raise RuntimeError("pyelftools required")
        self._fp = open(elf_path, 'rb')
        self.elf = ELFFile(self._fp)
        self.sym_by_addr, self.plt_to_sym, self.got_to_sym = {}, {}, {}
        self._parse_all()

    def close(self):
        if hasattr(self, '_fp') and self._fp:
            self._fp.close()

    def _parse_all(self):
        symtab = self.elf.get_section_by_name('.dynsym')
        if not symtab: return
        for sec_name in ['.dynsym', '.symtab']:
            sec = self.elf.get_section_by_name(sec_name)
            if not sec: continue
            for sym in sec.iter_symbols():
                if sym['st_value'] != 0 and sym['st_info']['type'] == 'STT_FUNC':
                    self.sym_by_addr[sym['st_value']] = sym.name
        plt_sec = self.elf.get_section_by_name('.plt')
        rela_plt = self.elf.get_section_by_name('.rela.plt') or self.elf.get_section_by_name('.rel.plt')
        if plt_sec and rela_plt:
            plt_base = plt_sec['sh_addr']
            rela_entries = list(rela_plt.iter_relocations())
            if rela_entries:
                plt_entry_size = plt_sec['sh_size'] // (len(rela_entries) + 1)
                for idx, rel in enumerate(rela_entries):
                    try:
                        name = symtab.get_symbol(rel['r_info_sym']).name
                        if name:
                            plt_addr = plt_base + (idx + 1) * plt_entry_size
                            self.plt_to_sym[hex(plt_addr).lower()] = name
                    except: continue
        def get_sym_name(rel):
            try: return symtab.get_symbol(rel['r_info_sym']).name
            except: return None
        for sec_name in ['.rela.plt', '.rel.plt', '.rela.dyn', '.rel.dyn']:
            sec = self.elf.get_section_by_name(sec_name)
            if sec:
                for rel in sec.iter_relocations():
                    off, name = rel['r_offset'], get_sym_name(rel)
                    if name and off: self.got_to_sym[hex(off).lower()] = name

    def match_ir_patterns(self, ir_path, call_map):
        replacements = {}
        with open(ir_path, 'r') as f: ir_content = f.read()
    
        func_patterns = [
            r'@(?:function_|sub_)(0x[0-9a-fA-F]+)(?!\w)',
            r'@(?:function_|sub_)(\d+)(?!\w)',
        ]
        got_pattern = re.compile(r'@global_var_(0x[0-9a-fA-F]+)')
     
        matched_count, debug_log = 0, []
    
        for pattern in func_patterns:
            func_pattern = re.compile(pattern)
            for m in func_pattern.finditer(ir_content):
                addr_str = m.group(1).lower()
                try: 
                    if addr_str.startswith('0x'):
                        addr_int = int(addr_str, 16)
                    else:
                        addr_int = int(addr_str)
                except ValueError: 
                    continue
                addr_hex = hex(addr_int).lower()
            
                sym = (self.plt_to_sym.get(addr_hex) or 
                       self.sym_by_addr.get(addr_int) or 
                       self.got_to_sym.get(addr_hex))
                if sym:
                    replacements[m.group(0)] = f"@{sym}"
                    matched_count += 1
                    debug_log.append(f"   {m.group(0)} -> @{sym} (0x{addr_int:x})")
    
        for m in got_pattern.finditer(ir_content):
            if (sym := self.got_to_sym.get(m.group(1).lower())):
                replacements[m.group(0)] = f"@{sym}"; matched_count += 1
    
        if matched_count > 0:
            print(f"[INFO] Found in ELF:")
            print(f"   - Symbol functions: {len(self.sym_by_addr)}")
            print(f"   - PLT stubs: {len(self.plt_to_sym)}")
            print(f"   - GOT entries: {len(self.got_to_sym)}")
            if debug_log:
                print(" Applied replacements:")
                for log in debug_log: print(log)
            print(f"[INFO] IR patterns matched & replaced: {matched_count}")
    
        return replacements


def auto_resolve(elf_path, ir_path):
    resolver = None
    try:
        resolver = ELFRelocResolver(elf_path)
        temp_call_map = defaultdict(set)
        with open(ir_path, 'r') as f:
            for line in f:
                if (m := re.search(r'define\s+[^@]*?@(\w+)\s*\(.*?call\s+.*?@(\w+)', line)):
                    temp_call_map[f"@{m.group(1)}"].add(f"@{m.group(2)}")
        replacements = resolver.match_ir_patterns(ir_path, temp_call_map)
        root = "@main"
        with open(ir_path, 'r') as f: ir_content = f.read()
        if "@main" not in ir_content:
            if (first := re.search(r'define\s+[^@]*?@(\w+)\s*\(', ir_content)):
                root = f"@{first.group(1)}"
            else: root = "@_init"
        return root, replacements
    finally:
        if resolver: resolver.close()


def get_shared_libraries(binary_path):
    try:
        result = subprocess.run(['ldd', binary_path], capture_output=True, text=True, check=True)
        libs, binary_dir = [], os.path.dirname(os.path.abspath(binary_path))
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if not line or 'linux-vdso' in line or 'linux-gate' in line: continue
            if '=>' in line:
                parts = line.split('=>', 1)
                if len(parts) == 2 and (path_part := parts[1].strip().split('(')[0].strip()):
                    lib_path = os.path.normpath(os.path.join(binary_dir, path_part)) if path_part.startswith('./') or path_part.startswith('../') else path_part
                    if os.path.exists(lib_path): libs.append((parts[0].strip(), lib_path))
            elif '.so' in line and '(' in line and '=>' not in line and (lib_path := line.split('(')[0].strip()) and os.path.basename(lib_path).endswith('.so'):
                if lib_path.startswith('./') or lib_path.startswith('../'): lib_path = os.path.normpath(os.path.join(binary_dir, lib_path))
                if os.path.exists(lib_path): libs.append((os.path.basename(lib_path), lib_path))
        return libs
    except Exception as e:
        print(f"[ERROR] Failed to run ldd: {e}"); return []


def extract_functions_from_ir(ir_path):
    functions, func_re = [], re.compile(r'^define\s+[^@]*?@(\w+)\s*\(')
    with open(ir_path, 'r', encoding='utf-8') as f:
        for line in f:
            if (m := func_re.match(line.strip())): functions.append("@" + m.group(1))
    return functions


def find_common_functions(funcs1, funcs2):
    libc = {"puts", "printf", "system", "getenv", "strncpy", "strstr", "__cxa_finalize", "__gmon_start__", "memcpy", "memset", "malloc", "free"}
    return sorted([f for f in set(funcs1).intersection(funcs2) if f.lstrip('@') not in libc])


def merge_dot_files(dot1_path, dot2_path, common_func, output_path):
    def parse_dot(filepath):
        nodes, edges, content = {}, [], open(filepath, 'r', encoding='utf-8').read()
        for m in re.finditer(r'"([^"]+)"\s*\[([^\]]+)\];', content): nodes[m.group(1)] = m.group(2).strip()
        for m in re.finditer(r'"([^"]+)"\s*->\s*"([^"]+)";', content): edges.append((m.group(1), m.group(2)))
        return nodes, edges
    nodes1, edges1 = parse_dot(dot1_path)
    nodes2, edges2 = parse_dot(dot2_path)
    if common_func in nodes2:
        attrs = nodes2[common_func].replace('fillcolor="#fff176"', 'fillcolor="#e1f5fe"').replace('penwidth=2', '')
        nodes2[common_func] = re.sub(r',\s*,', ',', attrs).strip().strip(',')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('digraph CallGraph {\n  rankdir=TB;\n  node [shape=box, style=filled, fillcolor="#e1f5fe", fontname="Arial", fontsize=10];\n')
        for func, attrs in {**nodes1, **nodes2}.items(): f.write(f'  "{func}" [{attrs}];\n')
        for src, dst in sorted(set(edges1 + edges2)): f.write(f'  "{src}" -> "{dst}";\n')
        f.write('}\n')
    print(f"[INFO] Merged graph saved: {output_path}")


def resolve_chain(func: str, replacements: dict) -> str:
    visited, curr = set(), func
    while curr in replacements and curr not in visited:
        visited.add(curr); curr = replacements[curr]
    return curr


def find_best_root(func_logic: dict, call_map: dict) -> str:
    for name in ["@main", "@_start", "@__libc_start_main", "@entry"]:
        if name in func_logic:
            return name
    if call_map:
        return max(call_map.keys(), key=lambda f: len(call_map[f]))
    return next(iter(func_logic.keys()), "@_init")


def build_and_print_graph(root: str, call_map: dict, func_logic: dict, replacements: dict) -> list:
    edges, visited = [], set()
    def dfs(func, depth=0):
        resolved = resolve_chain(func, replacements)
        if resolved in visited: return
        visited.add(resolved)
        prefix = "  " * depth
        logic = func_logic.get(resolved, {"globals": set(), "calls": set(), "entry_block": "?"})
        print(f"{prefix}{resolved} (entry: {logic['entry_block']})")
        print(f"{prefix}Globals: {', '.join(sorted(logic['globals'])) if logic['globals'] else '-'}")
        print(f"{prefix}Calls:   {', '.join(sorted(logic['calls'])) if logic['calls'] else '-'}")
        for reg in logic.get("indirect_regs", set()):
            if (target := resolve_chain(reg, replacements)) and target != resolved and not target.startswith("%"):
                call_map[resolved].add(target); func_logic[resolved]["calls"].add(target)
        for callee in sorted(call_map.get(resolved, set())):
            if (rc := resolve_chain(callee, replacements)) != resolved:
                edges.append((resolved, rc)); dfs(rc, depth + 1)
    dfs(root); return edges


def export_dot(edges: list, root: str, func_logic: dict, output_path: str, large_graph: bool = False):
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('digraph CallGraph {\n')
        f.write('  rankdir=TB;\n')
        
        if large_graph or len(edges) > 500:
            f.write('  size="100,100";\n')
            f.write('  ratio=compress;\n')
            f.write('  node [shape=box, style=filled, fillcolor="#e1f5fe", fontname="Arial", fontsize=8];\n')
            f.write('  overlap=scale;\n')
        else:
            f.write('  node [shape=box, style=filled, fillcolor="#e1f5fe", fontname="Arial", fontsize=10];\n')

        nodes = set()
        for src, dst in edges:
            nodes.update([src, dst])
            for node in [src, dst]:
                logic = func_logic.get(node, {"globals": set(), "calls": set()})
                if large_graph or len(nodes) > 200:
                    label = node
                else:
                    label = f"{node}\\nGlobals: {len(logic['globals'])} | Calls: {len(logic['calls'])}"
                f.write(f'  "{node}" [label="{label}"];\n')

        f.write(f'  "{root}" [fillcolor="#fff176", penwidth=2];\n')
        for p, c in edges:
            f.write(f'  "{p}" -> "{c}";\n')
        f.write('}\n')
    
    print(f"\n[INFO] Graph saved: {output_path}")


def get_top_shared_libraries(binary_path, limit=3):
    """Получает пути к топ-N разделяемым библиотекам бинарника через ldd"""
    try:
        result = subprocess.run(['ldd', binary_path], capture_output=True, text=True, check=True)
        libs = []
        for line in result.stdout.split('\n'):
            if '=>' in line:
                parts = line.split('=>')
                path = parts[1].split('(')[0].strip()
                if path and os.path.exists(path) and 'linux-vdso' not in path and 'linux-gate' not in path:
                    libs.append(path)
        # Убираем дубликаты, сохраняя порядок
        unique_libs = []
        seen = set()
        for lib in libs:
            if lib not in seen:
                unique_libs.append(lib)
                seen.add(lib)
        return unique_libs[:limit]
    except Exception as e:
        print(f"[WARN] Could not run ldd: {e}")
        return []


def export_merged_dot(main_call_map, main_func_logic, lib_data_list, output_path):
    """
    Экспортирует объединённый граф: основной бинарь + библиотеки.
    Функции-мосты (связывающие бинарь и библиотеки) выделяются жёлтым.
    
    lib_data_list: список словарей вида {
        'lib_name': str,
        'call_map': dict,
        'func_logic': dict,
        'bridge_functions': set  # функции-мосты из этой библиотеки
    }
    """
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('digraph MergedCallGraph {\n')
        f.write('  rankdir=TB;\n')
        f.write('  node [shape=box, style=filled, fontname="Arial", fontsize=10];\n')
        f.write('  edge [color="#666666"];\n\n')
        
        # Собираем все узлы и помечаем их тип
        all_nodes = {}  # func_name -> {'attrs': ..., 'type': 'main'|'lib'|'bridge'}
        all_edges = set()
        
        # 1. Основной бинарь
        for func, logic in main_func_logic.items():
            calls_count = len(logic.get("calls", set()))
            globals_count = len(logic.get("globals", set()))
            label = f"{func}\\n[G:{globals_count}, C:{calls_count}]"
            all_nodes[func] = {'label': label, 'type': 'main'}
        
        for caller, callees in main_call_map.items():
            for callee in callees:
                all_edges.add((caller, callee))
        
        # 2. Библиотеки
        all_bridge_functions = set()
        for lib_data in lib_data_list:
            lib_name = lib_data['lib_name']
            lib_call_map = lib_data['call_map']
            lib_func_logic = lib_data['func_logic']
            bridges = lib_data['bridge_functions']
            all_bridge_functions.update(bridges)
            
            for func, logic in lib_func_logic.items():
                # Пропускаем, если уже есть (например, та же функция определена в основном бинаре)
                if func in all_nodes:
                    continue
                calls_count = len(logic.get("calls", set()))
                globals_count = len(logic.get("globals", set()))
                label = f"{func}\\n[{lib_name}] G:{globals_count}, C:{calls_count}"
                all_nodes[func] = {'label': label, 'type': 'lib'}
            
            for caller, callees in lib_call_map.items():
                for callee in callees:
                    all_edges.add((caller, callee))
        
        # 3. Записываем узлы с разными цветами
        for func, info in all_nodes.items():
            safe_func = func.replace('"', '\\"')
            safe_label = info['label'].replace('"', '\\"')
            
            if func in all_bridge_functions:
                # Жёлтый — функция-мост
                fillcolor = "#ffff99"
                penwidth = "2.5"
            elif info['type'] == 'main':
                # Голубой — основной бинарь
                fillcolor = "#e1f5fe"
                penwidth = "1"
            else:
                # Зелёный — библиотечная функция
                fillcolor = "#e8f5e9"
                penwidth = "1"
            
            f.write(f'  "{safe_func}" [label="{safe_label}", fillcolor="{fillcolor}", penwidth={penwidth}];\n')
        
        f.write('\n')
        
        # 4. Записываем рёбра
        for src, dst in sorted(all_edges):
            safe_src = src.replace('"', '\\"')
            safe_dst = dst.replace('"', '\\"')
            f.write(f'  "{safe_src}" -> "{safe_dst}";\n')
        
        # 5. Легенда
        f.write('\n  subgraph cluster_legend {\n')
        f.write('    label="Legend";\n')
        f.write('    style=dashed;\n')
        f.write('    fontsize=10;\n')
        f.write('    legend_main [label="Main binary", fillcolor="#e1f5fe", shape=box];\n')
        f.write('    legend_bridge [label="Bridge function", fillcolor="#ffff99", shape=box, penwidth=2.5];\n')
        f.write('    legend_lib [label="Library function", fillcolor="#e8f5e9", shape=box];\n')
        f.write('  }\n')
        
        f.write('}\n')
    
    print(f"[SUCCESS] Merged graph saved: {output_path}")
    print(f"[INFO] Total nodes: {len(all_nodes)}, Total edges: {len(all_edges)}, Bridges: {len(all_bridge_functions)}")


# ==================== [C] АВТОМАТИЧЕСКИЙ РЕЖИМ (БЕЗ ИНТЕРАКТИВА) ====================

def automatic_mode(binary_path, output_dir=None):
    """
    Полностью автоматический режим анализа без интерактивных промптов.
    1. Анализирует основной бинарь
    2. Анализирует 3 библиотеки через ldd
    3. Объединяет всё в один DOT-файл
    4. LL-файлы сохраняются в поддиректории ll_files/
    """
    print("="*70 + "\n[INFO] AUTOMATIC BINARY ANALYSIS + LIBRARY MERGING\n" + "="*70)
    
    if not os.path.exists(binary_path):
        print(f"[ERROR] Binary file not found: {binary_path}")
        return None
    
    binary_name = os.path.basename(binary_path)
    binary_dir = os.path.dirname(os.path.abspath(binary_path))
    
    if output_dir is None:
        output_dir = binary_dir
    os.makedirs(output_dir, exist_ok=True)
    
    # === СОЗДАЁМ ОТДЕЛЬНУЮ ДИРЕКТОРИЮ ДЛЯ LL-ФАЙЛОВ ===
    ll_dir = os.path.join(output_dir, "ll_files")
    os.makedirs(ll_dir, exist_ok=True)
    print(f"[INFO] LLVM IR files will be stored in: {ll_dir}")
    
    # ===================== ШАГ 1: Основной бинарь =====================
    print(f"\n[STEP 1] LLVM IR generation for {binary_name}")
    main_ir = generate_llvm_ir_from_binary(binary_path, output_ll_path=ll_dir)
    
    if not main_ir or not os.path.exists(main_ir):
        print(f"[ERROR] Failed to generate LLVM IR. Analysis cannot proceed.")
        return None
    
    # ===================== ШАГ 2: Парсинг основного бинаря =====================
    print(f"\n[STEP 2] Parsing main binary LLVM IR...")
    main_call_map, main_func_logic = parse_llvm_ir(main_ir)
    print(f"[INFO] Parsed {len(main_func_logic)} defined functions.")
    
    # ===================== ШАГ 3: Heuristic Resolution =====================
    print(f"\n[STEP 3] Running Multi-Level Heuristic Resolution...")
    replacements = run_multi_level_resolution(main_call_map, main_func_logic, main_ir, binary_path)
    
    if replacements:
        main_call_map = apply_replacements_to_call_map(main_call_map, replacements)
        main_func_logic = apply_replacements_to_func_logic(main_func_logic, replacements)
        print(f"[INFO] Applied {len(replacements)} replacements")
    
    # ===================== ШАГ 4: Построение CFG основного бинаря =====================
    print(f"\n[STEP 4] Building CFG for main binary...")
    root = find_best_root(main_func_logic, main_call_map)
    if not root:
        print("[ERROR] No root found.")
        return None
    
    print(f"[INFO] Root function: {root}")
    edges = build_and_print_graph(root, main_call_map, main_func_logic, replacements)
    
    # Сохраняем отдельный DOT для основного бинаря
    main_dot = os.path.join(output_dir, f"{os.path.splitext(binary_name)[0]}_final_cfg.dot")
    large_graph = len(edges) > 500 or len(main_func_logic) > 200
    export_dot(edges, root, main_func_logic, main_dot, large_graph=large_graph)
    
    # ===================== ШАГ 5: Анализ 3-х библиотек =====================
    print(f"\n[STEP 5] Identifying top 3 shared libraries...")
    libs = get_top_shared_libraries(binary_path, limit=3)
    
    if not libs:
        print("[WARN] No shared libraries found. Skipping library analysis.")
        print(f"\n{'='*70}")
        print(f"[SUCCESS] Analysis complete (main binary only)!")
        print(f"[OUTPUT] Final DOT: {main_dot}")
        print("="*70)
        return main_dot
    
    print(f"[INFO] Found {len(libs)} libraries:")
    for i, lib_path in enumerate(libs, 1):
        print(f"  {i}. {os.path.basename(lib_path)}")
    
    lib_data_list = []
    
    for i, lib_path in enumerate(libs, 1):
        lib_name = os.path.basename(lib_path)
        print(f"\n[STEP 5.{i}] Processing library: {lib_name}")
        
        # Генерируем .ll для библиотеки в той же ll_dir
        print(f"  [*] Generating LLVM IR for {lib_name}...")
        lib_ir = generate_llvm_ir_from_binary(lib_path, output_ll_path=ll_dir, timeout=900)
        
        if not lib_ir or not os.path.exists(lib_ir):
            print(f"  [WARN] Skipped {lib_name} (failed to generate IR or timeout)")
            continue
        
        # Парсим IR библиотеки
        print(f"  [*] Parsing {lib_name} IR...")
        lib_call_map, lib_func_logic = parse_llvm_ir(lib_ir)
        print(f"  [INFO] Parsed {len(lib_func_logic)} functions in {lib_name}")
        
        # Ищем функции-мосты
        bridge_functions = set()
        lib_defined_funcs_lower = {func.lower(): func for func in lib_func_logic.keys()}
        
        for caller, callees in main_call_map.items():
            for callee in callees:
                callee_lower = callee.lower()
                
                matched_lib_func = None
                if callee_lower in lib_defined_funcs_lower:
                    matched_lib_func = lib_defined_funcs_lower[callee_lower]
                else:
                    callee_bare = callee.lstrip('@')
                    if len(callee_bare) > 3:
                        for lib_func_name in lib_defined_funcs_lower.keys():
                            if callee_bare in lib_func_name:
                                matched_lib_func = lib_defined_funcs_lower[lib_func_name]
                                break
                
                if matched_lib_func:
                    bridge_functions.add(matched_lib_func)
        
        print(f"  [INFO] Found {len(bridge_functions)} bridge functions in {lib_name}")
        if bridge_functions:
            for bf in sorted(list(bridge_functions))[:10]:
                print(f"    - {bf}")
            if len(bridge_functions) > 10:
                print(f"    ... and {len(bridge_functions) - 10} more")
        
        lib_data_list.append({
            'lib_name': lib_name,
            'call_map': lib_call_map,
            'func_logic': lib_func_logic,
            'bridge_functions': bridge_functions
        })
    
    # ===================== ШАГ 6: Объединение в один DOT =====================
    print(f"\n[STEP 6] Building merged CFG...")
    merged_dot = os.path.join(output_dir, f"{os.path.splitext(binary_name)[0]}_merged_cfg.dot")
    export_merged_dot(main_call_map, main_func_logic, lib_data_list, merged_dot)
    
    print(f"\n{'='*70}")
    print(f"[SUCCESS] Analysis complete!")
    print(f"[OUTPUT] Main binary DOT: {main_dot}")
    print(f"[OUTPUT] Merged DOT (with libraries): {merged_dot}")
    print(f"[OUTPUT] LLVM IR files directory: {ll_dir}")
    print(f"[INFO] To generate PNG:")
    print(f"  dot -Tpng {main_dot} -o {os.path.splitext(main_dot)[0]}.png")
    print(f"  dot -Tpng {merged_dot} -o {os.path.splitext(merged_dot)[0]}.png")
    print("="*70)
    
    return merged_dot


# ==================== [D] ИНТЕРАКТИВНЫЙ РЕЖИМ (ОПЦИОНАЛЬНО) ====================

def interactive_mode():
    print("="*70 + "\n[INFO] INTERACTIVE BINARY ANALYSIS WORKFLOW\n" + "="*70)
    
    main_binary = input("\n[STEP 1] Enter main binary path:\n> ").strip()
    if not os.path.exists(main_binary):
        print(f"[ERROR] File not found: {main_binary}")
        return
    
    # Создаём ll_files в директории бинаря
    binary_dir = os.path.dirname(os.path.abspath(main_binary))
    ll_dir = os.path.join(binary_dir, "ll_files")
    os.makedirs(ll_dir, exist_ok=True)
    print(f"[INFO] LLVM IR files will be stored in: {ll_dir}")
    
    print(f"\n[STEP 2] LLVM IR generation for {os.path.basename(main_binary)}")
    main_ir = generate_llvm_ir_from_binary(main_binary, output_ll_path=ll_dir)
    
    if not main_ir or not os.path.exists(main_ir):
        print(f"[ERROR] Failed to generate LLVM IR. Analysis cannot proceed.")
        return
    
    print(f"\n[STEP 3] Parsing LLVM IR...")
    call_map, func_logic = parse_llvm_ir(main_ir)
    print(f"[INFO] Parsed {len(func_logic)} defined functions.")
    
    print(f"\n[STEP 4] Running Multi-Level Heuristic Resolution...")
    replacements = run_multi_level_resolution(call_map, func_logic, main_ir, main_binary)
    
    if replacements:
        call_map = apply_replacements_to_call_map(call_map, replacements)
        func_logic = apply_replacements_to_func_logic(func_logic, replacements)
    
    print(f"\n[STEP 5] Building CFG...")
    root = find_best_root(func_logic, call_map)
    edges = build_and_print_graph(root, call_map, func_logic, replacements)
    
    output_dot = f"{os.path.splitext(main_binary)[0]}_final_cfg.dot"
    large_graph = len(edges) > 500 or len(func_logic) > 200
    export_dot(edges, root, func_logic, output_dot, large_graph=large_graph)
    
    print(f"\n[SUCCESS] Final DOT saved: {output_dot}")

def main():
    if len(sys.argv) > 1:
        binary_path = sys.argv[1]
        output_dir = sys.argv[2] if len(sys.argv) > 2 else None
        automatic_mode(binary_path, output_dir)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
