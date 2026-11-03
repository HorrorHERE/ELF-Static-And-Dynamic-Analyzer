#!/usr/bin/env python3
"""
Скрипт для сравнения результатов анализа Ghidra, IDA PRO и Custom Tool
с валидационными данными (Frida traces).
Рассчитывает TP, FP, FN, Precision, Recall, F1.
"""
import os
import re
import csv
import sys

# ==================== ПАРСЕРЫ ====================

def normalize_name(name: str) -> str:
    """Приводит имя функции к единому формату: lowercase, без мусора."""
    name = name.strip().lower()
    name = name.replace('@plt', '')
    name = name.lstrip('.@')
    # Убираем адреса в скобках или после \n
    name = re.split(r'[\n(]', name)[0].strip()
    return name

def parse_validation_dot(filepath: str) -> set:
    """Парсит файлы validation_traces/"""
    funcs = set()
    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read()
        # [label="NAME@plt\nADDR"] или [label="NAME\nADDR"]
        for match in re.finditer(r'\[label="([^\\]+)\\n', content):
            name = normalize_name(match.group(1))
            if name and name not in ['in', 'graph']:
                funcs.add(name)
    except Exception as e:
        print(f"[WARN] Error parsing {filepath}: {e}")
    return funcs

def parse_ghidra_dot(filepath: str) -> set:
    """Парсит файлы cfg_ghidra/"""
    funcs = set()
    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read()
        # [label="NAME\n(0xADDR)"]
        for match in re.finditer(r'\[label="([^\\]+)\\n', content):
            name = normalize_name(match.group(1))
            if name and not name.startswith('fun_') and 'call graph' not in name:
                funcs.add(name)
    except Exception as e:
        print(f"[WARN] Error parsing {filepath}: {e}")
    return funcs

def parse_ida_dot(filepath: str) -> set:
    """Парсит файлы cfg_idapro/"""
    funcs = set()
    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read()
        # IDA использует subgraph cluster_XXXX { label=".name"; ... }
        # Ищем label=".name" или label="name"
        for match in re.finditer(r'label\s*=\s*"\.?([^"]+)"', content):
            name = normalize_name(match.group(1))
            if name and 'bb_' not in name and 'graph' not in name:
                funcs.add(name)
    except Exception as e:
        print(f"[WARN] Error parsing {filepath}: {e}")
    return funcs

def parse_tool_dot(filepath: str) -> set:
    """Парсит файлы cfg_tool/ (только _merged_cfg.dot)"""
    funcs = set()
    try:
        with open(filepath, 'r', errors='ignore') as f:
            content = f.read()
        # Узлы имеют вид: "@function_XXXX" [label=...
        for match in re.finditer(r'"@([^"]+)"\s*\[label=', content):
            name = normalize_name(match.group(1))
            if name:
                funcs.add(name)
    except Exception as e:
        print(f"[WARN] Error parsing {filepath}: {e}")
    return funcs

# ==================== МЕТРИКИ ====================

def calculate_metrics(ground_truth: set, prediction: set) -> dict:
    tp = len(ground_truth & prediction)
    fp = len(prediction - ground_truth)
    fn = len(ground_truth - prediction)
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return {
        'TP': tp, 'FP': fp, 'FN': fn,
        'Precision': precision, 'Recall': recall, 'F1': f1
    }

def extract_base_name(filename: str) -> str:
    """Извлекает имя бинарника из имени файла валидации (например, aa-enabled_frida.dot -> aa-enabled)"""
    return re.sub(r'_frida\.dot$', '', filename)

# ==================== ОСНОВНАЯ ЛОГИКА ====================

def main():
    base_dir = os.getcwd()
    dirs = {
        'val': os.path.join(base_dir, 'validation_traces'),
        'val_full': os.path.join(base_dir, 'validation_full_traces'),
        'ghidra': os.path.join(base_dir, 'cfg_ghidra'),
        'ida': os.path.join(base_dir, 'cfg_idapro'),
        'tool': os.path.join(base_dir, 'cfg_tool')
    }
    
    # Проверяем существование директорий
    for name, path in dirs.items():
        if not os.path.exists(path):
            print(f"[ERROR] Directory not found: {path}")
            return

    # Собираем список всех бинарников из валидации
    binaries = set()
    for f in os.listdir(dirs['val']):
        if f.endswith('_frida.dot'):
            binaries.add(extract_base_name(f))
    
    binaries = sorted(binaries)
    print(f"[*] Найдено {len(binaries)} бинарников для сравнения.")
    
    results = []
    
    for bin_name in binaries:
        # Пути к файлам
        val_file = os.path.join(dirs['val'], f"{bin_name}_frida.dot")
        val_full_file = os.path.join(dirs['val_full'], f"{bin_name}_frida.dot")
        ghidra_file = os.path.join(dirs['ghidra'], f"call_graph_{bin_name}.dot")
        ida_file = os.path.join(dirs['ida'], f"{bin_name}.cfg.dot")
        tool_file = os.path.join(dirs['tool'], f"{bin_name}_merged_cfg.dot")
        
        # Парсим
        val_funcs = parse_validation_dot(val_file) if os.path.exists(val_file) else set()
        val_full_funcs = parse_validation_dot(val_full_file) if os.path.exists(val_full_file) else set()
        ghidra_funcs = parse_ghidra_dot(ghidra_file) if os.path.exists(ghidra_file) else set()
        ida_funcs = parse_ida_dot(ida_file) if os.path.exists(ida_file) else set()
        tool_funcs = parse_tool_dot(tool_file) if os.path.exists(tool_file) else set()
        
        # Считаем метрики
        metrics = {
            'binary': bin_name,
            'ghidra_vs_val': calculate_metrics(val_funcs, ghidra_funcs),
            'ghidra_vs_val_full': calculate_metrics(val_full_funcs, ghidra_funcs),
            'ida_vs_val': calculate_metrics(val_funcs, ida_funcs),
            'ida_vs_val_full': calculate_metrics(val_full_funcs, ida_funcs),
            'tool_vs_val': calculate_metrics(val_funcs, tool_funcs),
            'tool_vs_val_full': calculate_metrics(val_full_funcs, tool_funcs),
        }
        results.append(metrics)
    
    # === ВЫВОД РЕЗУЛЬТАТОВ ===
    print("\n" + "="*100)
    print("РЕЗУЛЬТАТЫ СРАВНЕНИЯ АНАЛИЗАТОРОВ")
    print("="*100)
    
    # Заголовки таблицы
    header = f"{'Binary':<25} | {'Tool':<8} | {'Dataset':<12} | {'TP':>4} | {'FP':>4} | {'FN':>4} | {'Prec':>6} | {'Rec':>6} | {'F1':>6}"
    print(header)
    print("-" * 100)
    
    for r in results:
        b = r['binary']
        for tool, ds_prefix in [('GHIDRA', 'ghidra'), ('IDA', 'ida'), ('TOOL', 'tool')]:
            for ds_name in ['val', 'val_full']:
                m = r[f"{ds_prefix}_vs_{ds_name}"]
                ds_label = "traces" if ds_name == "val" else "full_traces"
                print(f"{b:<25} | {tool:<8} | {ds_label:<12} | {m['TP']:>4} | {m['FP']:>4} | {m['FN']:>4} | {m['Precision']:>6.3f} | {m['Recall']:>6.3f} | {m['F1']:>6.3f}")
    
    print("="*100)
    
    # === ИТОГОВАЯ СВОДКА ===
    print("\n[*] ИТОГОВЫЕ СРЕДНИЕ МЕТРИКИ:")
    print("-" * 80)
    print(f"{'Tool':<10} | {'Dataset':<12} | {'Avg Precision':>13} | {'Avg Recall':>10} | {'Avg F1':>8}")
    print("-" * 80)
    
    summary = {}
    for tool in ['ghidra', 'ida', 'tool']:
        for ds in ['val', 'val_full']:
            key = f"{tool}_vs_{ds}"
            precisions = [r[key]['Precision'] for r in results if r[key]['Precision'] > 0]
            recalls = [r[key]['Recall'] for r in results if r[key]['Recall'] > 0]
            f1s = [r[key]['F1'] for r in results if r[key]['F1'] > 0]
            
            avg_p = sum(precisions)/len(precisions) if precisions else 0
            avg_r = sum(recalls)/len(recalls) if recalls else 0
            avg_f = sum(f1s)/len(f1s) if f1s else 0
            
            ds_label = "traces" if ds == "val" else "full_traces"
            print(f"{tool.upper():<10} | {ds_label:<12} | {avg_p:>13.4f} | {avg_r:>10.4f} | {avg_f:>8.4f}")
            
            summary[f"{tool.upper()} ({ds_label})"] = (avg_p, avg_r, avg_f)

    # === СОХРАНЕНИЕ В CSV ===
    csv_path = os.path.join(base_dir, 'comparison_results.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Binary', 'Tool', 'Dataset', 'TP', 'FP', 'FN', 'Precision', 'Recall', 'F1'])
        for r in results:
            b = r['binary']
            for tool, ds_prefix in [('GHIDRA', 'ghidra'), ('IDA', 'ida'), ('TOOL', 'tool')]:
                for ds_name in ['val', 'val_full']:
                    m = r[f"{ds_prefix}_vs_{ds_name}"]
                    ds_label = "traces" if ds_name == "val" else "full_traces"
                    writer.writerow([b, tool, ds_label, m['TP'], m['FP'], m['FN'], 
                                     round(m['Precision'], 4), round(m['Recall'], 4), round(m['F1'], 4)])
    print(f"\n[+] Детальные результаты сохранены в: {csv_path}")

if __name__ == "__main__":
    main()
